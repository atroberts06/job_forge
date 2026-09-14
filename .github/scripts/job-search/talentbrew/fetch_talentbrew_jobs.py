"""Fetch TalentBrew company-slot jobs, normalize, filter, write jobs.json."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

_JOB_SEARCH = Path(__file__).resolve().parents[1]
if str(_JOB_SEARCH) not in sys.path:
    sys.path.insert(0, str(_JOB_SEARCH))

from common.clock import now_iso
from common.validate_job_search import (
    company_enabled_boards,
    repo_root_from_here,
    validate_file as validate_instance,
)
from greenhouse.fetch_greenhouse_jobs import (
    close_missing_on_prior,
    load_existing_day,
    load_json,
    matches_criteria,
    merge_jobs,
    nearest_prior_jobs_path,
    prior_jobs_by_id,
    validate_pull_files,
)
from talentbrew.normalize import (
    PLATFORM,
    accepted_list_card,
    criteria_for_matching,
    normalize_talentbrew_job,
    parse_detail_page,
    parse_facet_catalog,
    parse_list_cards,
    resolve_facet_filters,
    titles_include_all,
)

CRITERIA_ID = "jsc_003"


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


def load_criteria_by_id(path: Path, criteria_id: str = CRITERIA_ID) -> dict[str, Any]:
    payload = load_json(path)
    rows = payload.get("criteria") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise RuntimeError(f"Criteria file must be an envelope with criteria[]: {path}")
    for row in rows:
        if isinstance(row, dict) and row.get("id") == criteria_id:
            if row.get("pipeline") != "talentbrew":
                raise RuntimeError(f"Criteria {criteria_id} is not pipeline=talentbrew")
            return row
    raise RuntimeError(f"Criteria id missing: {criteria_id}")


def _int_knob(criteria: dict[str, Any], key: str, *, minimum: int | None = None) -> int:
    raw = criteria.get(key)
    if type(raw) is not int:
        raise RuntimeError(f"jsc_003.{key} must be an integer")
    if minimum is not None and raw < minimum:
        raise RuntimeError(f"jsc_003.{key} must be >= {minimum}")
    return raw


def _optional_int(criteria: dict[str, Any], key: str) -> int | None:
    raw = criteria.get(key)
    if raw is None:
        return None
    if type(raw) is not int or raw < 1:
        raise RuntimeError(f"jsc_003.{key} must be null or an integer >= 1")
    return raw


def http_get(
    url: str,
    *,
    origin: str,
    timeout_seconds: int,
    max_retries: int,
    retry_status_codes: list[int],
    accept: str,
) -> tuple[int, bytes]:
    headers = {
        "User-Agent": "job-forge-job-search/1.0",
        "Accept": accept,
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"{origin.rstrip('/')}/search-jobs",
    }
    req = urllib.request.Request(url, headers=headers, method="GET")
    attempts = max_retries + 1
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
                return resp.getcode() or 200, resp.read()
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if exc.code in retry_status_codes and attempt + 1 < attempts:
                continue
            raise RuntimeError(f"TalentBrew HTTP {exc.code} for {url}: {exc.reason}") from exc
        except urllib.error.URLError as exc:
            last_exc = exc
            if attempt + 1 < attempts:
                continue
            raise RuntimeError(f"TalentBrew request failed for {url}: {exc.reason}") from exc
    raise RuntimeError(f"TalentBrew request failed for {url}: {last_exc}")


def build_list_url(
    origin: str,
    criteria: dict[str, Any],
    page: int,
    facet_filters: list[dict[str, str]] | None = None,
) -> str:
    query: list[tuple[str, str]] = [
        ("ActiveFacetID", str(_int_knob(criteria, "active_facet_id", minimum=0))),
        ("CurrentPage", str(page)),
        ("RecordsPerPage", str(_int_knob(criteria, "records_per_page", minimum=1))),
        ("Distance", str(_int_knob(criteria, "distance", minimum=0))),
        ("RadiusUnitType", str(_int_knob(criteria, "radius_unit_type", minimum=0))),
        ("Keywords", "" if criteria.get("search_keywords") is None else str(criteria.get("search_keywords"))),
        ("Location", "" if criteria.get("search_location") is None else str(criteria.get("search_location"))),
        ("ShowRadius", "True" if criteria.get("show_radius") is True else "False"),
        ("SearchResultsModuleName", "Search Results"),
        ("SearchFiltersModuleName", "Search Filters"),
        ("SortCriteria", str(_int_knob(criteria, "sort_criteria", minimum=0))),
        ("SortDirection", str(_int_knob(criteria, "sort_direction", minimum=0))),
        ("SearchType", str(_int_knob(criteria, "search_type", minimum=0))),
    ]
    for index, facet in enumerate(facet_filters or []):
        query.append((f"FacetFilters[{index}][ID]", facet["id"]))
        query.append((f"FacetFilters[{index}][FacetType]", facet.get("facet_type") or ""))
        query.append((f"FacetFilters[{index}][FieldName]", facet.get("field_name") or ""))
    return f"{origin.rstrip('/')}/search-jobs/results?{urllib.parse.urlencode(query)}"


def list_title_keep(card: dict[str, str], criteria: dict[str, Any]) -> bool:
    title = card.get("title") or ""
    exclude = ((criteria.get("titles") or {}).get("exclude") or [])
    include = ((criteria.get("titles") or {}).get("include") or [])
    title_l = title.lower()
    if any(str(item).lower() in title_l for item in exclude if item):
        return False
    if titles_include_all(criteria):
        return True
    if include and not any(str(item).lower() in title_l for item in include if item):
        return False
    return True


def list_geo_keep(card: dict[str, str], criteria: dict[str, Any]) -> bool:
    wlt_cfg = criteria.get("work_location_type") or {}
    if wlt_cfg.get("include_remote", True):
        return True
    location = card.get("location") or ""
    include_locations = ((criteria.get("locations") or {}).get("include") or [])
    if not include_locations:
        return True
    loc_l = location.lower()
    return any(str(item).lower() in loc_l for item in include_locations if item)


def fetch_list_page(
    origin: str,
    criteria: dict[str, Any],
    page: int,
    *,
    facet_filters: list[dict[str, str]] | None,
    timeout_seconds: int,
    max_retries: int,
    retry_status_codes: list[int],
) -> dict[str, Any]:
    url = build_list_url(origin, criteria, page, facet_filters)
    _status, body = http_get(
        url,
        origin=origin,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        retry_status_codes=retry_status_codes,
        accept="application/json, text/javascript, */*; q=0.01",
    )
    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"TalentBrew list response is not JSON: {url}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"TalentBrew list response is not an object: {url}")
    return payload


def collect_matched_jobs(
    boards: list[dict[str, str]],
    criteria: dict[str, Any],
    *,
    pull_date_str: str,
    status_updated_at: str,
    prior_jobs: dict[str, dict[str, Any]] | None = None,
    force_status: str | None = None,
    delay_s: float = 0.0,
) -> tuple[list[dict[str, Any]], int, int]:
    timeout_seconds = _int_knob(criteria, "timeout_seconds", minimum=1)
    max_retries = _int_knob(criteria, "max_retries", minimum=0)
    raw_codes = criteria.get("retry_status_codes")
    if not isinstance(raw_codes, list) or not raw_codes or not all(type(c) is int for c in raw_codes):
        raise RuntimeError("jsc_003.retry_status_codes must be a non-empty int array")
    retry_status_codes = list(raw_codes)
    max_pages = _optional_int(criteria, "max_pages")
    match_criteria = criteria_for_matching(criteria)
    matched: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    fetched_total = 0
    detail_gets = 0

    for board in boards:
        origin = board["career_url"]
        board_token = board["board_token"]
        company = board["company"]
        facet_filters: list[dict[str, str]] | None = None
        page = 1
        restarted_with_facets = False
        while True:
            if max_pages is not None and page > max_pages:
                break
            payload = fetch_list_page(
                origin,
                criteria,
                page,
                facet_filters=facet_filters,
                timeout_seconds=timeout_seconds,
                max_retries=max_retries,
                retry_status_codes=retry_status_codes,
            )
            if delay_s:
                time.sleep(delay_s)
            if page == 1 and facet_filters is None and not restarted_with_facets:
                catalog = parse_facet_catalog(str(payload.get("filters") or ""))
                facet_filters = resolve_facet_filters(criteria.get("facets") or {}, catalog)
                if facet_filters:
                    restarted_with_facets = True
                    page = 1
                    continue
            if payload.get("hasJobs") is False:
                break
            cards = parse_list_cards(str(payload.get("results") or ""))
            if not cards:
                break
            fetched_total += len(cards)
            for card in cards:
                accepted = accepted_list_card(card)
                if accepted is None:
                    print("WARNING: Skipping TalentBrew card with disagreeing href/data-job-id", file=sys.stderr)
                    continue
                if not list_title_keep(accepted, criteria) or not list_geo_keep(accepted, criteria):
                    continue
                href = accepted["href"]
                detail_url = urllib.parse.urljoin(origin.rstrip("/") + "/", href.lstrip("/"))
                _status, detail_body = http_get(
                    detail_url,
                    origin=origin,
                    timeout_seconds=timeout_seconds,
                    max_retries=max_retries,
                    retry_status_codes=retry_status_codes,
                    accept="text/html,application/xhtml+xml",
                )
                detail_gets += 1
                if delay_s:
                    time.sleep(delay_s)
                detail = parse_detail_page(detail_body.decode("utf-8", errors="replace"))
                try:
                    normalized = normalize_talentbrew_job(
                        accepted,
                        detail,
                        board_token=board_token,
                        company=company,
                        origin=origin,
                        pull_date=pull_date_str,
                        status_updated_at=status_updated_at,
                        prior_jobs=prior_jobs,
                        force_status=force_status,
                    )
                except ValueError as exc:
                    print(f"WARNING: Skipping job on {board_token}: {exc}", file=sys.stderr)
                    continue
                if not matches_criteria(normalized, match_criteria):
                    continue
                if normalized["id"] in seen_ids:
                    continue
                seen_ids.add(normalized["id"])
                matched.append(normalized)
            page += 1

    matched.sort(key=lambda j: (j.get("company") or "", j.get("title") or "", j.get("id") or ""))
    return matched, fetched_total, detail_gets


def write_envelope(out_path: Path, jobs: list[dict[str, Any]], pulled_at: str) -> None:
    envelope = {
        "platform": PLATFORM,
        "pulled_at": pulled_at,
        "jobs": jobs,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(envelope, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pull TalentBrew jobs into jobs.json")
    parser.add_argument("--date", dest="pull_date", default=None, help="Pull date YYYY-MM-DD (default: today UTC)")
    parser.add_argument("--repo-root", default=None, help="Repository root path (default: auto-detect)")
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Overwrite today's jobs.json from live source; every row status=new; reject past dates.",
    )
    args = parser.parse_args(argv)

    root = Path(args.repo_root).resolve() if args.repo_root else repo_root_from_here()
    platform_root = root / ".ai" / "history" / "job-search" / "talentbrew"
    companies_path = root / ".ai" / "history" / "job-search" / "companies.json"
    criteria_path = root / ".ai" / "guardrails" / "locked-job-search-criteria.json"
    model_path = root / ".ai" / "guardrails" / "locked-job-search-data-model.json"
    src_root = platform_root / "src"

    for path in (companies_path, criteria_path, model_path):
        if not path.is_file():
            print(f"ERROR: Required file missing: {path}", file=sys.stderr)
            return 1

    catalog_errors = validate_instance(companies_path, model_path, repo_root=root)
    if catalog_errors:
        print("ERROR: companies.json validation failed:", file=sys.stderr)
        for err in catalog_errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    catalog = load_json(companies_path)
    try:
        criteria = load_criteria_by_id(criteria_path)
    except (OSError, json.JSONDecodeError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    boards = company_enabled_boards(catalog)
    if not boards:
        print("ERROR: companies.json contains no pullable company-slot sources", file=sys.stderr)
        return 1

    today = utc_today()
    pull_date = date.fromisoformat(args.pull_date) if args.pull_date else today
    if pull_date < today:
        print(
            f"ERROR: Past date rejected ({pull_date.isoformat()} < {today.isoformat()} UTC)",
            file=sys.stderr,
        )
        return 1
    if args.rebuild and pull_date != today:
        print(
            f"ERROR: --rebuild only allowed for today UTC ({today.isoformat()}), got {pull_date.isoformat()}",
            file=sys.stderr,
        )
        return 1

    pull_date_str = pull_date.isoformat()
    status_updated_at = now_iso()
    pulled_at = now_iso()
    out_path = src_root / pull_date_str / "jobs.json"
    delay_s = _int_knob(criteria, "request_delay_ms", minimum=0) / 1000.0

    try:
        if args.rebuild:
            matched, fetched_total, detail_gets = collect_matched_jobs(
                boards,
                criteria,
                pull_date_str=pull_date_str,
                status_updated_at=status_updated_at,
                prior_jobs={},
                force_status="new",
                delay_s=delay_s,
            )
            write_envelope(out_path, matched, pulled_at)
            today_jobs = matched
            new_count = len(matched)
            total = len(matched)
            mode = "rebuild"
        else:
            existing = load_existing_day(out_path)
            existing_jobs: list[dict[str, Any]] = list((existing or {}).get("jobs") or [])
            prior_jobs = prior_jobs_by_id(src_root, pull_date)
            matched, fetched_total, detail_gets = collect_matched_jobs(
                boards,
                criteria,
                pull_date_str=pull_date_str,
                status_updated_at=status_updated_at,
                prior_jobs=prior_jobs,
                delay_s=delay_s,
            )
            merged, appended = merge_jobs(existing_jobs, matched)
            write_envelope(out_path, merged, pulled_at)
            today_jobs = merged
            new_count = appended
            total = len(merged)
            mode = "merge"
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    today_ids = {str(job.get("id")) for job in today_jobs if job.get("id")}
    prior_path = nearest_prior_jobs_path(src_root, pull_date)
    closed_count = 0
    prior_rel = ""
    if prior_path is not None:
        try:
            closed_count = close_missing_on_prior(prior_path, today_ids, status_updated_at)
        except (OSError, json.JSONDecodeError, RuntimeError) as exc:
            print(f"ERROR: Close-missing failed for {prior_path}: {exc}", file=sys.stderr)
            return 1
        try:
            prior_rel = str(prior_path.resolve().relative_to(root)).replace("\\", "/")
        except ValueError:
            prior_rel = str(prior_path).replace("\\", "/")

    to_validate = [out_path]
    if prior_path is not None:
        to_validate.append(prior_path)
    errors = validate_pull_files(to_validate, model_path)
    if errors:
        print("ERROR: Validation failed after pull/close-missing:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print(f"Platform: {PLATFORM}")
    print(f"Mode: {mode}")
    print(f"Boards: {len(boards)}")
    print(f"Fetched: {fetched_total}")
    print(f"Details: {detail_gets}")
    print(f"New: {new_count}")
    print(f"Total: {total}")
    print(f"Closed: {closed_count}")
    print(f"Output: {out_path}")
    if prior_rel:
        print(f"Prior: {prior_rel}")
    prior_token = prior_rel if prior_rel else "-"
    print(
        f"SUMMARY mode={mode} date={pull_date_str} new={new_count} "
        f"total={total} closed={closed_count} details={detail_gets} prior={prior_token}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
