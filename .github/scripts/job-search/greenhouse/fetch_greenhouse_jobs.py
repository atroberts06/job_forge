"""Fetch Greenhouse board jobs, normalize, filter by locked criteria, write jobs.json."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_JOB_SEARCH = Path(__file__).resolve().parents[1]
if str(_JOB_SEARCH) not in sys.path:
    sys.path.insert(0, str(_JOB_SEARCH))

from common.clock import now_iso
from common.validate_job_search import greenhouse_ats_boards, repo_root_from_here, validate_file as validate_instance
from common.validate_jobs import validate_file
from greenhouse.normalize import normalize_greenhouse_job

PLATFORM = "greenhouse"
API_URL = "https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true"


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


def load_json(path: Path) -> Any:
    if not path.is_file():
        raise FileNotFoundError(f"Required file missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_criteria_by_id(path: Path, criteria_id: str = "jsc_001") -> dict[str, Any]:
    payload = load_json(path)
    rows = payload.get("criteria") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise RuntimeError(f"Criteria file must be an envelope with criteria[]: {path}")
    for row in rows:
        if isinstance(row, dict) and row.get("id") == criteria_id:
            if row.get("pipeline") != "greenhouse":
                raise RuntimeError(f"Criteria {criteria_id} is not pipeline=greenhouse")
            return row
    raise RuntimeError(f"Criteria id missing: {criteria_id}")


def fetch_board_jobs(board_token: str, timeout: int = 60) -> list[dict[str, Any]]:
    url = API_URL.format(board_token=board_token)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "job-forge-job-search/1.0", "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Greenhouse API HTTP {exc.code} for board '{board_token}': {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Greenhouse API request failed for board '{board_token}': {exc.reason}") from exc

    jobs = payload.get("jobs")
    if not isinstance(jobs, list):
        raise RuntimeError(f"Unexpected Greenhouse response for board '{board_token}'")
    return jobs


def _contains_any(haystack: str, needles: list[str]) -> bool:
    lower = haystack.lower()
    return any(n.lower() in lower for n in needles if n)


def matches_criteria(job: dict[str, Any], criteria: dict[str, Any]) -> bool:
    title = str(job.get("title") or "")
    location = str(job.get("location") or "")
    description = str(job.get("description_text") or "")
    work_location_type = str(job.get("work_location_type") or "unknown")

    titles = criteria.get("titles") or {}
    include_titles = titles.get("include") or []
    exclude_titles = titles.get("exclude") or []
    if exclude_titles and _contains_any(title, exclude_titles):
        return False
    if include_titles and not _contains_any(title, include_titles):
        return False

    # Arrangement gate (work_location_type) — see Phase 1 plan diagram.
    wlt_cfg = criteria.get("work_location_type") or {}
    if work_location_type == "remote":
        if not wlt_cfg.get("include_remote", True):
            return False
        # remote bypasses geography entirely
    elif work_location_type in ("hybrid", "onsite"):
        toggle_key = f"include_{work_location_type}"
        if not wlt_cfg.get(toggle_key, True):
            return False
        # known non-remote: require geography match when include list is set
        locations = criteria.get("locations") or {}
        include_locations = locations.get("include") or []
        exclude_locations = locations.get("exclude") or []
        if exclude_locations and _contains_any(location, exclude_locations):
            return False
        if include_locations and not _contains_any(location, include_locations):
            return False
    else:
        # unknown always passes arrangement gate; geography only
        locations = criteria.get("locations") or {}
        include_locations = locations.get("include") or []
        exclude_locations = locations.get("exclude") or []
        if exclude_locations and _contains_any(location, exclude_locations):
            return False
        if include_locations and not _contains_any(location, include_locations):
            return False

    keywords = criteria.get("keywords") or {}
    include_keywords = keywords.get("include") or []
    exclude_keywords = keywords.get("exclude") or []
    apply_to = keywords.get("apply_to") or ["title", "description_text"]
    blob_parts: list[str] = []
    if "title" in apply_to:
        blob_parts.append(title)
    if "description_text" in apply_to:
        blob_parts.append(description)
    blob = " ".join(blob_parts)
    if exclude_keywords and _contains_any(blob, exclude_keywords):
        return False
    if include_keywords and not _contains_any(blob, include_keywords):
        return False

    return True


def nearest_prior_jobs_path(src_root: Path, pull_date: date) -> Path | None:
    """Single nearest prior dated jobs.json within 30 days (not a union)."""
    for offset in range(1, 31):
        prior = pull_date - timedelta(days=offset)
        path = src_root / prior.isoformat() / "jobs.json"
        if path.is_file():
            return path
    return None


def prior_jobs_by_id(src_root: Path, pull_date: date) -> dict[str, dict[str, Any]]:
    """Rows from the single nearest prior dated jobs.json within 30 days (not a union)."""
    path = nearest_prior_jobs_path(src_root, pull_date)
    if path is None:
        return {}
    try:
        data = load_json(path)
    except (OSError, json.JSONDecodeError):
        return {}
    rows: dict[str, dict[str, Any]] = {}
    for job in data.get("jobs") or []:
        if not isinstance(job, dict):
            continue
        job_id = job.get("id")
        if job_id and str(job_id) not in rows:
            rows[str(job_id)] = job
    return rows


def prior_job_ids(src_root: Path, pull_date: date) -> set[str]:
    """Ids from the single nearest prior dated jobs.json within 30 days (not a union)."""
    return set(prior_jobs_by_id(src_root, pull_date).keys())


def close_missing_on_prior(
    prior_path: Path,
    today_ids: set[str],
    status_updated_at: str,
) -> int:
    """Set status=closed on prior rows whose id is absent from today's file.

    Already-closed rows are a no-op. Other fields and envelope pulled_at are unchanged.
    Returns the number of rows newly closed.
    """
    data = load_json(prior_path)
    if not isinstance(data, dict):
        raise RuntimeError(f"Prior day file is not an object: {prior_path}")
    jobs = data.get("jobs")
    if not isinstance(jobs, list):
        raise RuntimeError(f"Prior day jobs must be an array: {prior_path}")

    closed_count = 0
    for job in jobs:
        if not isinstance(job, dict):
            continue
        job_id = str(job.get("id") or "")
        if not job_id or job_id in today_ids:
            continue
        if job.get("status") == "closed":
            continue
        job["status"] = "closed"
        job["status_updated_at"] = status_updated_at
        closed_count += 1

    if closed_count:
        prior_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return closed_count


def validate_pull_files(jobs_paths: list[Path], schema_path: Path) -> list[str]:
    errors: list[str] = []
    seen: set[Path] = set()
    for path in jobs_paths:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        errors.extend(validate_file(resolved, schema_path))
    return errors


def load_existing_day(out_path: Path) -> dict[str, Any] | None:
    if not out_path.is_file():
        return None
    try:
        data = load_json(out_path)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Existing day file unreadable: {out_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"Existing day file is not an object: {out_path}")
    return data


def collect_matched_jobs(
    boards: list[dict[str, Any]],
    criteria: dict[str, Any],
    *,
    pull_date_str: str,
    status_updated_at: str,
    prior_jobs: dict[str, dict[str, Any]] | None = None,
    prior_ids: set[str] | None = None,
    force_status: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    matched: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    fetched_total = 0

    for board in boards:
        board_token = str(board.get("board_token") or "").strip()
        company = str(board.get("company") or board_token).strip()
        if not board_token:
            raise RuntimeError("companies.json contains a Greenhouse ats row with empty board_token")
        raw_jobs = fetch_board_jobs(board_token)
        fetched_total += len(raw_jobs)
        for raw in raw_jobs:
            try:
                normalized = normalize_greenhouse_job(
                    raw,
                    board_token=board_token,
                    company=company,
                    pull_date=pull_date_str,
                    status_updated_at=status_updated_at,
                    prior_jobs=prior_jobs,
                    prior_ids=prior_ids,
                    force_status=force_status,
                )
            except ValueError as exc:
                print(f"WARNING: Skipping job on {board_token}: {exc}", file=sys.stderr)
                continue
            if not matches_criteria(normalized, criteria):
                continue
            if normalized["id"] in seen_ids:
                # Intra-fetch duplicate: first-wins
                continue
            seen_ids.add(normalized["id"])
            matched.append(normalized)

    matched.sort(key=lambda j: (j.get("company") or "", j.get("title") or "", j.get("id") or ""))
    return matched, fetched_total


def merge_jobs(
    existing_jobs: list[dict[str, Any]],
    fetched_jobs: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Append only unseen ids; existing rows and statuses are immutable. First-wins on fetch dups."""
    by_id: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for job in existing_jobs:
        job_id = str(job.get("id") or "")
        if not job_id or job_id in by_id:
            continue
        by_id[job_id] = job
        order.append(job_id)

    appended = 0
    for job in fetched_jobs:
        job_id = str(job.get("id") or "")
        if not job_id or job_id in by_id:
            continue
        by_id[job_id] = job
        order.append(job_id)
        appended += 1

    merged = [by_id[i] for i in order]
    merged.sort(key=lambda j: (j.get("company") or "", j.get("title") or "", j.get("id") or ""))
    return merged, appended


def write_envelope(out_path: Path, jobs: list[dict[str, Any]], pulled_at: str) -> None:
    envelope = {
        "platform": PLATFORM,
        "pulled_at": pulled_at,
        "jobs": jobs,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(envelope, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pull Greenhouse jobs into jobs.json")
    parser.add_argument(
        "--date",
        dest="pull_date",
        default=None,
        help="Pull date YYYY-MM-DD (default: today UTC)",
    )
    parser.add_argument(
        "--repo-root",
        default=None,
        help="Repository root path (default: auto-detect)",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Overwrite today's jobs.json from live source; every row status=new; reject past dates. "
        "Paired write_analysis_stubs.py --rebuild wipes pre-handoff analysis files and approved-jobs rows; "
        "skips in_progress|failed|completed|deployed.",
    )
    args = parser.parse_args(argv)

    root = Path(args.repo_root).resolve() if args.repo_root else repo_root_from_here()
    platform_root = root / ".ai" / "history" / "job-search" / "greenhouse"
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
    boards = greenhouse_ats_boards(catalog)
    if not boards:
        print("ERROR: companies.json contains no pullable Greenhouse ats sources", file=sys.stderr)
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

    if args.rebuild:
        # No lookback for today's statuses: every row is new. Close-missing still patches prior.
        matched, fetched_total = collect_matched_jobs(
            boards,
            criteria,
            pull_date_str=pull_date_str,
            status_updated_at=status_updated_at,
            prior_jobs={},
            force_status="new",
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
        matched, fetched_total = collect_matched_jobs(
            boards,
            criteria,
            pull_date_str=pull_date_str,
            status_updated_at=status_updated_at,
            prior_jobs=prior_jobs,
        )
        merged, appended = merge_jobs(existing_jobs, matched)
        write_envelope(out_path, merged, pulled_at)
        today_jobs = merged
        new_count = appended
        total = len(merged)
        mode = "merge"

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
    print(f"New: {new_count}")
    print(f"Total: {total}")
    print(f"Closed: {closed_count}")
    print(f"Output: {out_path}")
    if prior_rel:
        print(f"Prior: {prior_rel}")
    # Machine-readable summary for workflow commit messages (C3).
    prior_token = prior_rel if prior_rel else "-"
    print(
        f"SUMMARY mode={mode} date={pull_date_str} new={new_count} "
        f"total={total} closed={closed_count} prior={prior_token}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
