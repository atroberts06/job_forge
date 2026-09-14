"""Create pull-time analysis stubs and a missing approved-jobs.json envelope."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

_JOB_SEARCH = Path(__file__).resolve().parents[1]
if str(_JOB_SEARCH) not in sys.path:
    sys.path.insert(0, str(_JOB_SEARCH))

from common.clock import now_iso
from common.consume_analysis_queue import POST_HANDOFF_STATUSES
from common.validate_job_search import encode_job_id, load_json, repo_root_from_here, validate_file

DEFAULT_PLATFORM = "greenhouse"
PLATFORMS = ("greenhouse", "serpapi", "talentbrew")

STUB_TELEMETRY = {
    "started_at": None,
    "ended_at": None,
    "tokens_in": None,
    "tokens_out": None,
    "cache_tokens_in": None,
    "thinking_tokens": None,
    "context_usage_percent": None,
    "context_metric_status": "not_programmatically_available",
}


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


def stub_document(
    job_id: str, pull_date: str, updated_at: str, *, platform: str = DEFAULT_PLATFORM
) -> dict[str, Any]:
    return {
        "platform": platform,
        "job_id": job_id,
        "analysis_id": 0,
        "updated_at": updated_at,
        "analyses": [
            {
                "analysis_id": 0,
                "job_id": job_id,
                "pull_date": pull_date,
                "revision": 0,
                "is_current": True,
                "run_id": None,
                "analyzed_at": None,
                "decision": None,
                "justification": None,
                "experience": {"requirements": []},
                "skills": {"requirements": []},
                "constraints": {"requirements": []},
                "external_context": {"decision_impact": "none", "sources": []},
                **STUB_TELEMETRY,
            }
        ],
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def ledger_status_by_id(approved_path: Path) -> dict[str, str]:
    if not approved_path.is_file():
        return {}
    data = load_json(approved_path)
    jobs = data.get("jobs")
    if not isinstance(jobs, list):
        raise RuntimeError(f"approved-jobs.json jobs must be an array: {approved_path}")
    out: dict[str, str] = {}
    for row in jobs:
        if isinstance(row, dict) and row.get("id"):
            out[str(row["id"])] = str(row.get("status") or "")
    return out


def drop_approved_rows(approved_path: Path, job_ids: set[str]) -> int:
    if not approved_path.is_file():
        return 0
    data = load_json(approved_path)
    jobs = data.get("jobs")
    if not isinstance(jobs, list):
        raise RuntimeError(f"approved-jobs.json jobs must be an array: {approved_path}")
    kept: list[Any] = []
    for row in jobs:
        if (
            isinstance(row, dict)
            and str(row.get("id") or "") in job_ids
            and row.get("status") not in POST_HANDOFF_STATUSES
        ):
            continue
        kept.append(row)
    dropped = len(jobs) - len(kept)
    if dropped:
        data["jobs"] = kept
        write_json(approved_path, data)
    return dropped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write per-job analysis stubs after a platform pull")
    parser.add_argument("--date", dest="pull_date", default=None, help="Pull date YYYY-MM-DD (default: today UTC)")
    parser.add_argument("--repo-root", default=None)
    parser.add_argument(
        "--platform",
        default=DEFAULT_PLATFORM,
        choices=PLATFORMS,
        help="Sandbox platform folder under .ai/history/job-search/ (default: greenhouse)",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Today UTC only: delete+recreate analysis files for ids in today's jobs.json "
        "and drop matching pre-handoff approved-jobs.json rows. Skip sidecar wipe, "
        "ledger drop, and stub write for in_progress|failed|completed|deployed.",
    )
    args = parser.parse_args(argv)

    root = Path(args.repo_root).resolve() if args.repo_root else repo_root_from_here()
    platform = args.platform
    platform_root = root / ".ai" / "history" / "job-search" / platform
    src_root = platform_root / "src"
    analyses_dir = platform_root / "analyses"
    approved_path = platform_root / "approved-jobs.json"
    schema_path = root / ".ai" / "guardrails" / "locked-job-search-data-model.json"

    today = utc_today()
    pull_date = date.fromisoformat(args.pull_date) if args.pull_date else today
    if args.rebuild and pull_date != today:
        print(
            f"ERROR: --rebuild only allowed for today UTC ({today.isoformat()}), got {pull_date.isoformat()}",
            file=sys.stderr,
        )
        return 1

    jobs_path = src_root / pull_date.isoformat() / "jobs.json"
    if not jobs_path.is_file():
        print(f"ERROR: jobs file missing: {jobs_path}", file=sys.stderr)
        return 1
    if not schema_path.is_file():
        print(f"ERROR: schema missing: {schema_path}", file=sys.stderr)
        return 1

    envelope = load_json(jobs_path)
    jobs = envelope.get("jobs") or []
    job_ids = [str(job.get("id")) for job in jobs if isinstance(job, dict) and job.get("id")]
    updated_at = now_iso()
    pull_date_str = pull_date.isoformat()
    written: list[Path] = []
    created_approved = False

    analyses_dir.mkdir(parents=True, exist_ok=True)
    protected = {
        job_id
        for job_id, status in ledger_status_by_id(approved_path).items()
        if status in POST_HANDOFF_STATUSES
    }
    encoded_seen: dict[str, str] = {}
    for job_id in job_ids:
        encoded = encode_job_id(job_id)
        if encoded in encoded_seen and encoded_seen[encoded] != job_id:
            print(
                f"ERROR: filename collision encoding {job_id!r} and {encoded_seen[encoded]!r} to {encoded}",
                file=sys.stderr,
            )
            return 1
        encoded_seen[encoded] = job_id
        dest = analyses_dir / f"{encoded}-analysis.json"
        if args.rebuild and job_id in protected:
            continue
        if args.rebuild and dest.is_file():
            dest.unlink()
        if dest.is_file():
            continue
        write_json(dest, stub_document(job_id, pull_date_str, updated_at, platform=platform))
        written.append(dest)

    if args.rebuild:
        drop_approved_rows(approved_path, set(job_ids))

    if not approved_path.is_file():
        write_json(
            approved_path,
            {"platform": platform, "jobs": []},
        )
        created_approved = True
        written.append(approved_path)

    errors: list[str] = []
    for path in written:
        require_stub = path.name.endswith("-analysis.json")
        errors.extend(
            validate_file(
                path,
                schema_path,
                repo_root=root,
                require_stub=require_stub,
            )
        )
    if errors:
        print("ERROR: Stub validation failed:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print(f"Platform: {platform}")
    print(f"Mode: {'rebuild' if args.rebuild else 'create-if-not-exists'}")
    print(f"Stubs written: {sum(1 for p in written if p.name.endswith('-analysis.json'))}")
    print(f"Approved envelope created: {str(created_approved).lower()}")
    print(f"Analyses: {analyses_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
