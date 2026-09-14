"""Fetch SerpApi Google Jobs, normalize, filter, and write jobs.json."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from calendar import monthrange
from datetime import date
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve()
_SERP_API_DIR = _HERE.parent
_JOB_SEARCH = Path(__file__).resolve().parents[1]
if str(_SERP_API_DIR) not in sys.path:
    sys.path.insert(0, str(_SERP_API_DIR))
if str(_JOB_SEARCH) not in sys.path:
    sys.path.insert(0, str(_JOB_SEARCH))

from common.clock import now_iso
from common.validate_job_search import (
    career_site_origin,
    url_contains_ats_identity,
    url_contains_company_name,
    validate_file as validate_instance,
)
from greenhouse.fetch_greenhouse_jobs import (
    load_existing_day,
    load_json,
    matches_criteria,
    merge_jobs,
    nearest_prior_jobs_path,
    prior_jobs_by_id,
    utc_today,
    validate_pull_files,
)
from normalize_serpapi import DATE_POSTED_CATALOG, kebab_case, normalize_serpapi_job

PLATFORM = "serpapi"
ACCOUNT_URL = "https://serpapi.com/account.json"
SEARCH_URL = "https://serpapi.com/search.json"


def repo_root_from_here() -> Path:
    return _HERE.parents[4]


def load_criteria_by_id(path: Path, criteria_id: str) -> dict[str, Any]:
    payload = load_json(path)
    rows = payload.get("criteria") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise RuntimeError(f"Criteria file must be an envelope with criteria[]: {path}")
    for row in rows:
        if isinstance(row, dict) and row.get("id") == criteria_id:
            if row.get("pipeline") != "google_jobs":
                raise RuntimeError(f"Criteria {criteria_id} is not pipeline=google_jobs")
            return row
    raise RuntimeError(f"Criteria id missing: {criteria_id}")


def _int_field(payload: dict[str, Any], key: str, default: int = 0) -> int:
    try:
        return int(payload.get(key, default) or default)
    except (TypeError, ValueError):
        return default


def days_remaining_in_utc_month(today: date | None = None) -> int:
    current = today or utc_today()
    return monthrange(current.year, current.month)[1] - current.day + 1


def daily_cap_from_account(account: dict[str, Any], max_searches: int) -> int:
    left = _int_field(account, "plan_searches_left")
    days_remaining = max(days_remaining_in_utc_month(), 1)
    return min(max_searches, left // days_remaining)


def _url_with_params(url: str, params: dict[str, Any]) -> str:
    clean = {key: value for key, value in params.items() if value not in (None, "")}
    return f"{url}?{urllib.parse.urlencode(clean)}"


def http_get_json(url: str, params: dict[str, Any], timeout: int = 60) -> dict[str, Any]:
    req = urllib.request.Request(
        _url_with_params(url, params),
        headers={"User-Agent": "job-forge-job-search/1.0", "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"SerpApi HTTP {exc.code}: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"SerpApi request failed: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("SerpApi returned invalid JSON") from exc


def fetch_account(api_key: str) -> dict[str, Any]:
    return http_get_json(ACCOUNT_URL, {"api_key": api_key})


def fetch_google_jobs(api_key: str, params: dict[str, Any]) -> dict[str, Any]:
    request_params = dict(params)
    request_params["api_key"] = api_key
    request_params["engine"] = "google_jobs"
    return http_get_json(SEARCH_URL, request_params)


def build_fan_out(criteria: dict[str, Any]) -> list[tuple[str, str | None]]:
    terms = [str(term).strip() for term in (criteria.get("search_query") or {}).get("include") or [] if str(term).strip()]
    locations = [
        str(location).strip()
        for location in (criteria.get("location") or {}).get("include") or []
        if str(location).strip()
    ]
    if not terms:
        return []
    if locations:
        return [(term, location) for term in terms for location in locations]
    return [(term, None) for term in terms]


def build_search_params(criteria: dict[str, Any], term: str, location: str | None, date_filter: dict[str, str]) -> dict[str, Any]:
    parts = [term]
    industry = str(criteria.get("industry_query") or "").strip()
    if industry:
        parts.append(industry)
    parts.append(date_filter["q_suffix"])
    params: dict[str, Any] = {
        "q": " ".join(part for part in parts if part).strip(),
        "uds": date_filter["uds"],
        "gl": criteria.get("country_code"),
        "hl": criteria.get("language_code"),
        "google_domain": criteria.get("google_domain"),
        "location": location,
    }
    if criteria.get("include_remote"):
        params["ltype"] = 1
    radius = criteria.get("search_radius_kilometers")
    if radius not in (None, ""):
        params["radius"] = radius
    return params


def load_max_searches(criteria: dict[str, Any]) -> int:
    raw = criteria.get("max_searches")
    if type(raw) is not int or raw < 1:
        raise RuntimeError("Criteria jsc_002 max_searches must be an integer >= 1")
    return raw


def planned_requests(criteria: dict[str, Any], date_filter: dict[str, str]) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    for term, location in build_fan_out(criteria):
        params = build_search_params(criteria, term, location, date_filter)
        requests.append({"page": 1, "params": params})
        requests.append({"page": 2, "params": dict(params, next_page_token="<runtime>")})
    return requests


def _is_cached(payload: dict[str, Any]) -> bool:
    metadata = payload.get("search_metadata") if isinstance(payload.get("search_metadata"), dict) else {}
    metadata_id = str(metadata.get("id") or "")
    return metadata_id.startswith("cached_") or bool(metadata.get("cached"))


def _status_success(payload: dict[str, Any]) -> bool:
    metadata = payload.get("search_metadata") if isinstance(payload.get("search_metadata"), dict) else {}
    return metadata.get("status") == "Success"


def _next_page_token(payload: dict[str, Any]) -> str | None:
    pagination = payload.get("serpapi_pagination") if isinstance(payload.get("serpapi_pagination"), dict) else {}
    token = str(pagination.get("next_page_token") or "").strip()
    return token or None


def _quota_values(account: dict[str, Any], monthly_limit_arg: int, max_searches: int, billable_this_run: int) -> tuple[int, int, int, int]:
    searches_per_month = _int_field(account, "searches_per_month", monthly_limit_arg)
    monthly_limit = min(monthly_limit_arg, searches_per_month)
    used = _int_field(account, "this_month_usage")
    left = _int_field(account, "plan_searches_left")
    daily_cap = daily_cap_from_account(account, max_searches)
    print(f"QUOTA used={used} left={left} daily_cap={daily_cap} billable_this_run={billable_this_run}")
    return used, left, daily_cap, monthly_limit


def can_search(account: dict[str, Any], *, monthly_limit: int, max_searches: int, billable_this_run: int) -> bool:
    used = _int_field(account, "this_month_usage")
    left = _int_field(account, "plan_searches_left")
    daily_cap = daily_cap_from_account(account, max_searches)
    return left > 0 and used < monthly_limit and billable_this_run < max_searches and billable_this_run < daily_cap


def collect_serpapi_jobs(
    *,
    api_key: str,
    criteria: dict[str, Any],
    date_filter: dict[str, str],
    pull_date_str: str,
    status_updated_at: str,
    prior_jobs: dict[str, dict[str, Any]],
    force_status: str | None,
    max_searches: int,
    monthly_limit_arg: int,
) -> tuple[list[dict[str, Any]], int, int]:
    normalized: list[dict[str, Any]] = []
    raw_total = 0
    billable_this_run = 0
    search_http_count = 0

    first_account = fetch_account(api_key)
    used, left, daily_cap, monthly_limit = _quota_values(first_account, monthly_limit_arg, max_searches, billable_this_run)
    planned = len(build_fan_out(criteria)) * 2
    if planned > left or planned > max_searches or planned > daily_cap:
        print("QUOTA_STOP")
        return [], 0, 0

    for term, location in build_fan_out(criteria):
        base_params = build_search_params(criteria, term, location, date_filter)
        for page in (1, 2):
            params = dict(base_params)
            if page == 2:
                token = _next_page_token(payload)
                if not token:
                    break
                params["next_page_token"] = token

            account = fetch_account(api_key)
            _, _, _, monthly_limit = _quota_values(account, monthly_limit_arg, max_searches, billable_this_run)
            if not can_search(account, monthly_limit=monthly_limit, max_searches=max_searches, billable_this_run=billable_this_run):
                if billable_this_run == 0:
                    print("QUOTA_STOP")
                return normalized, raw_total, search_http_count

            payload = fetch_google_jobs(api_key, params)
            search_http_count += 1
            if not _status_success(payload):
                raise RuntimeError("SerpApi google_jobs search_metadata.status was not Success")
            if not _is_cached(payload):
                billable_this_run += 1
            raw_jobs = payload.get("jobs_results") or []
            if not isinstance(raw_jobs, list):
                raise RuntimeError("SerpApi response jobs_results must be an array")
            raw_total += len(raw_jobs)
            for raw in raw_jobs:
                if not isinstance(raw, dict):
                    continue
                try:
                    normalized.append(
                        normalize_serpapi_job(
                            raw,
                            pull_date=pull_date_str,
                            status_updated_at=status_updated_at,
                            prior_jobs=prior_jobs,
                            force_status=force_status,
                        )
                    )
                except ValueError as exc:
                    print(f"WARNING: Skipping SerpApi job: {exc}", file=sys.stderr)
                    continue

    return normalized, raw_total, search_http_count


def dedupe_filter_sort(
    jobs: list[dict[str, Any]],
    criteria: dict[str, Any],
) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for job in jobs:
        job_id = str(job.get("id") or "")
        if not job_id or job_id in by_id:
            continue
        if not matches_criteria(job, criteria):
            continue
        by_id[job_id] = job
    rows = list(by_id.values())
    rows.sort(key=lambda j: (j.get("company") or "", j.get("title") or "", j.get("id") or ""))
    return rows


def write_envelope(out_path: Path, jobs: list[dict[str, Any]], pulled_at: str) -> None:
    envelope = {
        "platform": PLATFORM,
        "pulled_at": pulled_at,
        "jobs": jobs,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(envelope, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


SOURCE_DEFAULT = ""
SOURCE_MANUAL = "manual"
SOURCE_SERPAPI = "serpapi"


def _source_template(
    platform: str,
    board_token: str,
    career_url: str,
    source: str = SOURCE_DEFAULT,
    detected_at: str | None = None,
) -> dict[str, Any]:
    return {
        "enabled": False,
        "platform": platform,
        "board_token": board_token,
        "career_url": career_url,
        "source": source,
        "detected_at": detected_at,
    }


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not str(value).strip())


def _slot_is_manual_or_enabled(slot: dict[str, Any]) -> bool:
    return slot.get("enabled") is True or str(slot.get("source") or "") == SOURCE_MANUAL


def _fill_blank(slot: dict[str, Any], key: str, value: Any) -> bool:
    if _blank(value) or not _blank(slot.get(key)):
        return False
    slot[key] = value
    return True


def _stamp_first_fill(slot: dict[str, Any], filled: bool, detected_on: str) -> None:
    """Stamp pipeline source on first-fill only. Non-empty source is locked."""
    if not filled:
        return
    _fill_blank(slot, "source", SOURCE_SERPAPI)
    if _blank(slot.get("detected_at")):
        slot["detected_at"] = detected_on


ATS_URL_PLATFORMS = frozenset({"greenhouse", "lever", "ashby"})


def detect_ats_from_url(url: str, company_id: str) -> dict[str, str]:
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower()
    path_parts = [urllib.parse.unquote(part) for part in parsed.path.split("/") if part]

    if "greenhouse.io" in host:
        return {"platform": "greenhouse", "board_token": path_parts[0] if path_parts else company_id}
    if "lever.co" in host:
        return {"platform": "lever", "board_token": path_parts[0] if path_parts else company_id}
    if "ashbyhq.com" in host:
        return {"platform": "ashby", "board_token": path_parts[0] if path_parts else company_id}
    return {"platform": "unknown", "board_token": ""}


def upsert_companies(
    catalog_path: Path, kept_jobs: list[dict[str, Any]], detected_on: str
) -> None:
    catalog = load_json(catalog_path)
    rows = catalog.get("companies") if isinstance(catalog, dict) else None
    if not isinstance(rows, list):
        raise RuntimeError(f"companies.json must contain companies[]: {catalog_path}")

    by_id = {str(row.get("id")): row for row in rows if isinstance(row, dict) and row.get("id")}

    for job in kept_jobs:
        company_name = str(job.get("company") or "").strip()
        if not company_name:
            continue
        company_id = kebab_case(company_name)
        if not company_id:
            continue
        job_url = str(job.get("url") or "").strip()
        detected = detect_ats_from_url(job_url, company_id)
        is_ats_url = detected["platform"] in ATS_URL_PLATFORMS
        row = by_id.get(company_id)
        if row is None:
            row = {
                "id": company_id,
                "name": company_name,
                "company_url": "",
                "industries": [],
                "ats": _source_template("", "", "", ""),
                "company": _source_template(company_id, company_id, "", ""),
            }
            by_id[company_id] = row
            rows.append(row)
        # First-fill blank fields only. Never overwrite populated values.
        # source is stamped from the writing pipeline (serpapi) on first-fill, then locked.
        # manual source is user-owned: skip the slot. Never infer industries[] or company_url.
        existing_ats = row.get("ats") if isinstance(row.get("ats"), dict) else {}
        existing_company = row.get("company") if isinstance(row.get("company"), dict) else {}
        ats_url_ok = is_ats_url and url_contains_ats_identity(
            job_url, detected["platform"], detected["board_token"]
        )
        if existing_ats and not _slot_is_manual_or_enabled(existing_ats) and ats_url_ok:
            ats_filled = False
            ats_filled |= _fill_blank(existing_ats, "platform", detected["platform"])
            ats_filled |= _fill_blank(existing_ats, "board_token", detected["board_token"])
            ats_filled |= _fill_blank(existing_ats, "career_url", job_url)
            _stamp_first_fill(existing_ats, ats_filled, detected_on)
            row["ats"] = existing_ats
        if existing_company and not _slot_is_manual_or_enabled(existing_company):
            _fill_blank(existing_company, "platform", company_id)
            _fill_blank(existing_company, "board_token", company_id)
            display_name = str(row.get("name") or company_name)
            origin = career_site_origin(job_url)
            company_filled = False
            if not ats_url_ok and url_contains_company_name(origin, display_name):
                company_filled = _fill_blank(existing_company, "career_url", origin)
            _stamp_first_fill(existing_company, company_filled, detected_on)
            row["company"] = existing_company

    rows.sort(key=lambda item: (str(item.get("name") or ""), str(item.get("id") or "")))
    catalog_path.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _print_summary(mode: str, pull_date_str: str, new_count: int, total: int, closed: int, prior_rel: str) -> None:
    prior_token = prior_rel if prior_rel else "-"
    print(
        f"SUMMARY mode={mode} date={pull_date_str} new={new_count} "
        f"total={total} closed={closed} prior={prior_token}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pull SerpApi Google Jobs into jobs.json")
    parser.add_argument("--date", dest="pull_date", default=None)
    parser.add_argument("--repo-root", default=None)
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--monthly-limit", type=int, default=250)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    root = Path(args.repo_root).resolve() if args.repo_root else repo_root_from_here()
    platform_root = root / ".ai" / "history" / "job-search" / "serpapi"
    companies_path = root / ".ai" / "history" / "job-search" / "companies.json"
    criteria_path = root / ".ai" / "guardrails" / "locked-job-search-criteria.json"
    model_path = root / ".ai" / "guardrails" / "locked-job-search-data-model.json"
    src_root = platform_root / "src"
    today = utc_today()
    pull_date = date.fromisoformat(args.pull_date) if args.pull_date else today
    pull_date_str = pull_date.isoformat()
    out_path = src_root / pull_date_str / "jobs.json"

    api_key = os.environ.get("SERPAPI_API_KEY", "").strip()
    if not api_key:
        print("ERROR: SERPAPI_API_KEY is not set", file=sys.stderr)
        print("Platform: serpapi")
        print("Mode: skip")
        _print_summary("skip", pull_date_str, 0, 0, 0, "")
        return 0

    for path in (companies_path, criteria_path, model_path):
        if not path.is_file():
            print(f"ERROR: Required file missing: {path}", file=sys.stderr)
            return 1

    if out_path.is_file() and not args.rebuild:
        print("Platform: serpapi")
        print("Mode: skip")
        print(f"SKIP: {out_path} already exists")
        _print_summary("skip", pull_date_str, 0, 0, 0, "")
        return 0

    try:
        criteria = load_criteria_by_id(criteria_path, "jsc_002")
        date_key = str(criteria.get("date_posted") or "").strip()
        if not date_key:
            raise RuntimeError("Criteria jsc_002 missing required date_posted")
        date_filter = DATE_POSTED_CATALOG.get(date_key)
        if date_filter is None:
            raise RuntimeError(f"Unsupported date_posted value: {date_key}")
        fan_out = build_fan_out(criteria)
        if not fan_out:
            raise RuntimeError("Criteria jsc_002 produced zero SerpApi fan-out pairs")
        max_searches = load_max_searches(criteria)
    except (OSError, json.JSONDecodeError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.dry_run:
        try:
            account = fetch_account(api_key)
        except RuntimeError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        _quota_values(account, args.monthly_limit, max_searches, 0)
        requests = planned_requests(criteria, date_filter)
        print(f"DRY_RUN planned_searches={len(requests)}")
        for request in requests:
            params = request["params"]
            print(f"DRY_RUN page={request['page']} q={params.get('q')} uds={params.get('uds')}")
        _print_summary("dry-run", pull_date_str, 0, 0, 0, "")
        return 0

    status_updated_at = now_iso()
    pulled_at = now_iso()

    try:
        if args.rebuild:
            normalized, fetched_total, search_http_count = collect_serpapi_jobs(
                api_key=api_key,
                criteria=criteria,
                date_filter=date_filter,
                pull_date_str=pull_date_str,
                status_updated_at=status_updated_at,
                prior_jobs={},
                force_status="new",
                max_searches=max_searches,
                monthly_limit_arg=args.monthly_limit,
            )
            matched = dedupe_filter_sort(normalized, criteria)
            if not matched and search_http_count > 0:
                raise RuntimeError("Zero jobs survived SerpApi normalization/filtering")
            if not matched:
                print("Platform: serpapi")
                print("Mode: skip")
                _print_summary("skip", pull_date_str, 0, 0, 0, "")
                return 0
            write_envelope(out_path, matched, pulled_at)
            new_count = len(matched)
            total = len(matched)
            mode = "rebuild"
        else:
            existing = load_existing_day(out_path)
            existing_jobs: list[dict[str, Any]] = list((existing or {}).get("jobs") or [])
            prior_jobs = prior_jobs_by_id(src_root, pull_date)
            normalized, fetched_total, search_http_count = collect_serpapi_jobs(
                api_key=api_key,
                criteria=criteria,
                date_filter=date_filter,
                pull_date_str=pull_date_str,
                status_updated_at=status_updated_at,
                prior_jobs=prior_jobs,
                force_status=None,
                max_searches=max_searches,
                monthly_limit_arg=args.monthly_limit,
            )
            matched = dedupe_filter_sort(normalized, criteria)
            if not matched and search_http_count > 0:
                raise RuntimeError("Zero jobs survived SerpApi normalization/filtering")
            if not matched:
                print("Platform: serpapi")
                print("Mode: skip")
                _print_summary("skip", pull_date_str, 0, 0, 0, "")
                return 0
            merged, appended = merge_jobs(existing_jobs, matched)
            write_envelope(out_path, merged, pulled_at)
            new_count = appended
            total = len(merged)
            mode = "merge"

        upsert_companies(companies_path, matched, pull_date_str)

        prior_path = nearest_prior_jobs_path(src_root, pull_date)
        prior_rel = ""
        if prior_path is not None:
            try:
                prior_rel = str(prior_path.resolve().relative_to(root)).replace("\\", "/")
            except ValueError:
                prior_rel = str(prior_path).replace("\\", "/")

        catalog_errors = validate_instance(companies_path, model_path, repo_root=root)
        if catalog_errors:
            print("ERROR: companies.json validation failed:", file=sys.stderr)
            for err in catalog_errors:
                print(f"  - {err}", file=sys.stderr)
            return 1

        errors = validate_pull_files([out_path], model_path)
        if errors:
            print("ERROR: Validation failed after pull:", file=sys.stderr)
            for err in errors:
                print(f"  - {err}", file=sys.stderr)
            return 1
    except (OSError, json.JSONDecodeError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Platform: {PLATFORM}")
    print(f"Mode: {mode}")
    print(f"FanOut: {len(fan_out)}")
    print(f"Fetched: {fetched_total}")
    print(f"New: {new_count}")
    print(f"Total: {total}")
    print("Closed: 0")
    print(f"Output: {out_path}")
    if prior_rel:
        print(f"Prior: {prior_rel}")
    _print_summary(mode, pull_date_str, new_count, total, 0, prior_rel)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
