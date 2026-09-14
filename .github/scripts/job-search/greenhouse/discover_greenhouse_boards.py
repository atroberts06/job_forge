"""Discover Greenhouse board tokens from MyGreenhouse Inertia search and upsert new companies."""

from __future__ import annotations

import argparse
import itertools
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_JOB_SEARCH = Path(__file__).resolve().parents[1]
if str(_JOB_SEARCH) not in sys.path:
    sys.path.insert(0, str(_JOB_SEARCH))

from common.clock import now_iso
from common.validate_job_search import repo_root_from_here, validate_companies_semantic, validate_file
from greenhouse.chrome_cookie import get_my_greenhouse_session_cookie

MY_GREENHOUSE_SEARCH_URL = "https://my.greenhouse.io/jobs/search"
GREENHOUSE_BOARD_API_URL = "https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)


def utc_today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def kebab_case(value: str) -> str:
    slug = value.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")


def load_json(path: Path) -> Any:
    if not path.is_file():
        raise FileNotFoundError(f"Required file missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_discovery_criteria(path: Path, criteria_id: str = "jsc_004") -> dict[str, Any]:
    payload = load_json(path)
    rows = payload.get("criteria") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise RuntimeError(f"Criteria file must contain criteria[] array: {path}")
    for row in rows:
        if isinstance(row, dict) and row.get("id") == criteria_id:
            if row.get("pipeline") != "greenhouse_discovery":
                raise RuntimeError(f"Criteria {criteria_id} has invalid pipeline: {row.get('pipeline')}")
            return row
    raise RuntimeError(f"Criteria ID missing: {criteria_id}")


def extract_board_token(url: str) -> str | None:
    if not url:
        return None
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return None

    qs = urllib.parse.parse_qs(parsed.query)
    if "for" in qs and qs["for"]:
        token = qs["for"][0].strip()
        if token and token.lower() != "internal":
            return token

    netloc = parsed.netloc.lower()
    if "greenhouse.io" in netloc:
        parts = [p.strip() for p in parsed.path.split("/") if p.strip()]
        if parts:
            if parts[0] in ("embed", "v1", "jobs", "users", "search"):
                return None
            return parts[0]

    return None


def extract_inertia_version_from_html(html: str) -> str | None:
    match = re.search(r'data-page="([^"]+)"', html)
    if match:
        try:
            page_data = json.loads(urllib.parse.unquote(match.group(1).replace("&quot;", '"')))
            version = page_data.get("version")
            if version:
                return str(version)
        except Exception:
            pass
    match_ver = re.search(r'["\']?version["\']?\s*:\s*["\']([^"\']+)["\']', html)
    if match_ver:
        return match_ver.group(1)
    return None


def fetch_inertia_version(session_cookie: str, timeout: int = 30) -> str:
    req = urllib.request.Request(
        MY_GREENHOUSE_SEARCH_URL,
        headers={
            "User-Agent": USER_AGENT,
            "Cookie": session_cookie,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            html = resp.read().decode("utf-8", errors="replace")
            ver = extract_inertia_version_from_html(html)
            if ver:
                return ver
    except Exception:
        pass
    return ""


def query_my_greenhouse_inertia(
    params: dict[str, Any],
    session_cookie: str,
    inertia_version: str = "",
    timeout: int = 30,
    max_retries: int = 3,
) -> dict[str, Any] | None:
    query_string = urllib.parse.urlencode(params, doseq=True)
    url = f"{MY_GREENHOUSE_SEARCH_URL}?{query_string}" if query_string else MY_GREENHOUSE_SEARCH_URL

    headers = {
        "User-Agent": USER_AGENT,
        "Cookie": session_cookie,
        "Accept": "text/html, application/xhtml+xml",
        "X-Inertia": "true",
        "X-Inertia-Partial-Component": "jobs",
        "X-Inertia-Partial-Data": "jobPosts,page,moreResultsAvailable,browsing",
    }
    if inertia_version:
        headers["X-Inertia-Version"] = inertia_version

    for attempt in range(max_retries + 1):
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                return {"_auth_failed": True, "_status": exc.code}
            if exc.code == 409:
                new_version = exc.headers.get("X-Inertia-Version") or ""
                if new_version and new_version != inertia_version:
                    headers["X-Inertia-Version"] = new_version
                    continue
                return None
            if exc.code in (429, 503) and attempt < max_retries:
                time.sleep((2**attempt) * 1.5)
                continue
            return None
        except (urllib.error.URLError, json.JSONDecodeError, OSError):
            if attempt < max_retries:
                time.sleep((2**attempt) * 1.5)
                continue
            return None
    return None


def parse_inertia_jobs_payload(payload: dict[str, Any]) -> tuple[list[dict[str, str]], int, int, bool]:
    """Extract job list and pagination from Inertia search response.
    Returns (extracted_jobs, current_page, total_pages, more_results_available)
    """
    if not isinstance(payload, dict):
        return [], 1, 1, False

    props = payload.get("props") or {}
    jobs_raw = (
        props.get("jobPosts")
        or props.get("jobs")
        or props.get("results")
        or props.get("search_results")
        or (props.get("searchResults") if isinstance(props.get("searchResults"), dict) else {}).get("jobs")
        or []
    )

    page = int(props.get("page") or 1)
    total_pages = int(props.get("total_pages") or props.get("totalPages") or 1)
    more_available = bool(props.get("moreResultsAvailable", False))

    extracted: list[dict[str, str]] = []
    if isinstance(jobs_raw, list):
        for item in jobs_raw:
            if not isinstance(item, dict):
                continue
            company_name = str(
                item.get("companyName")
                or item.get("company")
                or item.get("company_name")
                or item.get("organization")
                or ""
            ).strip()
            job_url = str(
                item.get("publicUrl")
                or item.get("url")
                or item.get("job_url")
                or item.get("apply_url")
                or item.get("absolute_url")
                or ""
            ).strip()

            board_token = str(item.get("urlToken") or "").strip()
            if not board_token:
                board_token = extract_board_token(job_url) or ""
            if not board_token and isinstance(item.get("board_token"), str):
                board_token = item["board_token"].strip()

            if company_name and board_token:
                extracted.append(
                    {
                        "company": company_name,
                        "board_token": board_token,
                        "url": job_url or f"https://job-boards.greenhouse.io/{board_token}",
                    }
                )

    return extracted, page, total_pages, more_available


def probe_board_reachability(board_token: str, timeout: int = 30) -> bool:
    """Check if the public Greenhouse board API endpoint is reachable and returns HTTP 200 with jobs array."""
    url = GREENHOUSE_BOARD_API_URL.format(board_token=board_token)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "job-forge-job-search/1.0", "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                payload = json.loads(resp.read().decode("utf-8"))
                return isinstance(payload.get("jobs"), list)
    except Exception:
        return False
    return False


def build_search_queries(search_chips: dict[str, Any]) -> list[dict[str, Any]]:
    """Build list of parameter dicts from Cartesian product of search chips."""
    search_terms = [s.strip() for s in (search_chips.get("search_term") or []) if s.strip()]
    if not search_terms:
        search_terms = [""]

    work_types = [w.strip() for w in (search_chips.get("work_type") or []) if w.strip()]
    employment_types = [e.strip() for e in (search_chips.get("employment_type") or []) if e.strip()]
    locations = [loc.strip() for loc in (search_chips.get("location") or []) if loc.strip()]
    date_posteds = [d.strip() for d in (search_chips.get("date_posted") or []) if d.strip()]

    combos: list[dict[str, Any]] = []
    for term in search_terms:
        params: dict[str, Any] = {}
        if term:
            params["query"] = term
        if work_types:
            params["work_type[]"] = work_types
        if employment_types:
            params["employment_type[]"] = employment_types
        if locations:
            params["location[]"] = locations
        if date_posteds:
            params["date_posted[]"] = date_posteds
        combos.append(params)

    return combos


def run_discovery(
    criteria: dict[str, Any],
    session_cookie: str,
    max_pages_override: int | None = None,
) -> tuple[list[dict[str, str]], bool]:
    """Execute search across chips and return discovered items and auth_ok flag."""
    search_chips = criteria.get("search_chips") or {}
    pagination = criteria.get("pagination") or {}

    max_pages = max_pages_override or int(pagination.get("max_pages_per_query") or 5)
    delay_ms = int(pagination.get("request_delay_ms") or 1000)
    timeout = int(pagination.get("timeout_seconds") or 30)
    max_retries = int(pagination.get("max_retries") or 3)

    version = fetch_inertia_version(session_cookie, timeout=timeout)
    queries = build_search_queries(search_chips)

    discovered: list[dict[str, str]] = []
    seen_tokens: set[str] = set()

    for query_params in queries:
        for page in range(1, max_pages + 1):
            page_params = dict(query_params)
            page_params["page"] = page

            res = query_my_greenhouse_inertia(
                page_params,
                session_cookie=session_cookie,
                inertia_version=version,
                timeout=timeout,
                max_retries=max_retries,
            )

            if res is None:
                break
            if res.get("_auth_failed"):
                return [], False

            items, current_page, total_pages, more_available = parse_inertia_jobs_payload(res)
            for item in items:
                tok_key = item["board_token"].lower()
                if tok_key not in seen_tokens:
                    seen_tokens.add(tok_key)
                    discovered.append(item)

            if not items or (not more_available and current_page >= total_pages):
                break

            if delay_ms > 0:
                time.sleep(delay_ms / 1000.0)

    return discovered, True


def deduplicate_against_catalog(
    discovered: list[dict[str, str]],
    catalog: dict[str, Any],
) -> list[dict[str, str]]:
    """Stage 1: Early deduplication against existing catalog companies."""
    existing_companies = catalog.get("companies") or []
    existing_ids = {str(c.get("id")) for c in existing_companies if isinstance(c, dict) and c.get("id")}
    existing_tokens = {
        str(c.get("ats", {}).get("board_token") or "").lower()
        for c in existing_companies
        if isinstance(c, dict) and c.get("ats", {}).get("board_token")
    }

    new_candidates: list[dict[str, str]] = []
    seen_in_batch: set[str] = set()

    for item in discovered:
        company_name = item.get("company", "").strip()
        board_token = item.get("board_token", "").strip()
        if not company_name or not board_token:
            continue

        company_id = kebab_case(company_name)
        if not company_id:
            continue

        if company_id in existing_ids:
            continue
        if board_token.lower() in existing_tokens:
            continue
        if company_id in seen_in_batch or board_token.lower() in seen_in_batch:
            continue

        seen_in_batch.add(company_id)
        seen_in_batch.add(board_token.lower())
        new_candidates.append(
            {
                "id": company_id,
                "name": company_name,
                "board_token": board_token,
                "url": item.get("url", f"https://job-boards.greenhouse.io/{board_token}"),
            }
        )

    return new_candidates


def insert_new_companies(
    catalog_path: Path,
    new_candidates: list[dict[str, str]],
    probe_verification: bool = True,
    timeout: int = 30,
) -> tuple[int, int, int]:
    """Stage 2 (Probe) & Stage 3 (Insert) into companies.json. Returns (new_count, enabled_count, disabled_count)."""
    if not new_candidates:
        return 0, 0, 0

    catalog = load_json(catalog_path)
    companies = catalog.get("companies")
    if not isinstance(companies, list):
        raise RuntimeError(f"companies.json must contain companies[]: {catalog_path}")

    today_iso = utc_today_iso()
    enabled_count = 0
    disabled_count = 0

    for cand in new_candidates:
        company_id = cand["id"]
        company_name = cand["name"]
        board_token = cand["board_token"]

        probe_passed = True
        if probe_verification:
            probe_passed = probe_board_reachability(board_token, timeout=timeout)

        if probe_passed:
            enabled_count += 1
        else:
            disabled_count += 1

        new_row = {
            "id": company_id,
            "name": company_name,
            "company_url": "",
            "industries": [],
            "ats": {
                "enabled": probe_passed,
                "platform": "greenhouse",
                "board_token": board_token,
                "career_url": f"https://job-boards.greenhouse.io/{board_token}",
                "source": "greenhouse_discovery",
                "detected_at": today_iso,
            },
            "company": {
                "enabled": False,
                "platform": company_id,
                "board_token": company_id,
                "career_url": "",
                "source": "",
                "detected_at": None,
            },
        }
        companies.append(new_row)

    companies.sort(key=lambda c: (str(c.get("name") or ""), str(c.get("id") or "")))
    catalog_path.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return len(new_candidates), enabled_count, disabled_count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Discover Greenhouse board tokens and normalize catalog")
    parser.add_argument("--repo-root", default=None, help="Repository root path")
    parser.add_argument("--session-cookie", default=None, help="Raw _my_greenhouse_session cookie string")
    parser.add_argument("--criteria-id", default="jsc_004", help="Discovery criteria row ID (default: jsc_004)")
    parser.add_argument("--dry-run", action="store_true", help="Scrape without writing to companies.json")
    parser.add_argument("--max-pages", type=int, default=None, help="Override max pages per query")
    parser.add_argument("--no-probe", action="store_true", help="Disable public board reachability probe")
    args = parser.parse_args(argv)

    root = Path(args.repo_root).resolve() if args.repo_root else repo_root_from_here()
    criteria_path = root / ".ai" / "guardrails" / "locked-job-search-criteria.json"
    companies_path = root / ".ai" / "history" / "job-search" / "companies.json"
    data_model_path = root / ".ai" / "guardrails" / "locked-job-search-data-model.json"

    for path in (criteria_path, companies_path, data_model_path):
        if not path.is_file():
            print(f"ERROR: Required file missing: {path}", file=sys.stderr)
            return 1

    try:
        criteria = load_discovery_criteria(criteria_path, criteria_id=args.criteria_id)
    except Exception as exc:
        print(f"ERROR: Failed to load criteria: {exc}", file=sys.stderr)
        return 1

    session_cookie = (args.session_cookie or "").strip()
    if not session_cookie:
        session_cookie = os.environ.get("GREENHOUSE_SESSION_COOKIE", "").strip()
    if not session_cookie:
        auth_file = root / ".auth" / "greenhouse_session.txt"
        if auth_file.is_file():
            session_cookie = auth_file.read_text(encoding="utf-8").strip()
    if not session_cookie:
        session_cookie = get_my_greenhouse_session_cookie() or ""

    if session_cookie and "=" not in session_cookie:
        session_cookie = f"_session_id={session_cookie}"

    if not session_cookie:
        print(
            "INFO: No active MyGreenhouse session found in browser, CLI, or .auth/greenhouse_session.txt. "
            "Please log into my.greenhouse.io in Chrome or pass -SessionCookie. Skipping discovery.",
            file=sys.stderr,
        )
        # Graceful exit 0 for scheduled tasks
        return 0

    discovered, auth_ok = run_discovery(
        criteria,
        session_cookie=session_cookie,
        max_pages_override=args.max_pages,
    )

    if not auth_ok:
        print(
            "INFO: MyGreenhouse session expired or rejected (401/403). "
            "Please re-authenticate at my.greenhouse.io in Chrome. Skipping discovery.",
            file=sys.stderr,
        )
        return 0

    catalog = load_json(companies_path)
    new_candidates = deduplicate_against_catalog(discovered, catalog)

    probe_verification = (not args.no_probe) and bool(criteria.get("probe_verification", True))
    timeout = int((criteria.get("pagination") or {}).get("timeout_seconds") or 30)

    if args.dry_run:
        print(f"Platform: greenhouse_discovery (DRY RUN)")
        print(f"Discovered Total: {len(discovered)}")
        print(f"New Candidates: {len(new_candidates)}")
        for cand in new_candidates:
            status = "enabled" if (not probe_verification or probe_board_reachability(cand["board_token"])) else "disabled"
            print(f"  - {cand['name']} ({cand['id']}) -> token: {cand['board_token']} [{status}]")
        return 0

    new_count, enabled_count, disabled_count = insert_new_companies(
        companies_path,
        new_candidates,
        probe_verification=probe_verification,
        timeout=timeout,
    )

    if new_count > 0:
        errors = validate_file(companies_path, data_model_path)
        if errors:
            print("ERROR: companies.json validation failed after insertion:", file=sys.stderr)
            for err in errors:
                print(f"  - {err}", file=sys.stderr)
            return 1

    print(f"Platform: greenhouse_discovery")
    print(f"Criteria: {args.criteria_id}")
    print(f"Discovered: {len(discovered)}")
    print(f"New: {new_count}")
    print(f"Enabled: {enabled_count}")
    print(f"Disabled: {disabled_count}")
    print(
        f"SUMMARY mode=discovery new={new_count} enabled={enabled_count} "
        f"disabled={disabled_count} total_discovered={len(discovered)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
