"""Copy pending tailor-queue rows onto approved-jobs.json as in_progress.

File-level claim. Orchestrator runs this locally before each tailor-file
invoke. Does not commit or push. Sets status and status_updated_at only.
started_at and attempt_count are owned by the resume-tailor skill.
Tailor must not write the ledger.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_JOB_SEARCH = Path(__file__).resolve().parents[1]
if str(_JOB_SEARCH) not in sys.path:
    sys.path.insert(0, str(_JOB_SEARCH))

from common.validate_job_search import load_json, repo_root_from_here, validate_file


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def ledger_path(root: Path, platform: str) -> Path:
    return root / ".ai" / "history" / "job-search" / platform / "approved-jobs.json"


def claim_file(root: Path, queue_path: Path, *, now: str) -> int:
    queue = load_json(queue_path)
    platform = str(queue.get("platform") or "").strip()
    if not platform:
        print(f"ERROR: {queue_path}: platform is required", file=sys.stderr)
        return 1
    path = ledger_path(root, platform)
    if not path.is_file():
        print(f"ERROR: ledger missing: {path}", file=sys.stderr)
        return 1
    ledger = load_json(path)
    jobs = ledger.setdefault("jobs", [])
    if not isinstance(jobs, list):
        print("ERROR: ledger jobs must be an array", file=sys.stderr)
        return 1

    claimed = 0
    for row in queue.get("jobs") or []:
        if not isinstance(row, dict) or row.get("status") != "pending":
            continue
        job_id = str(row.get("id") or "")
        existing = next((item for item in jobs if item.get("id") == job_id), None)
        if existing is None:
            print(f"ERROR: ledger row missing for {job_id}", file=sys.stderr)
            return 1
        existing["status"] = "in_progress"
        existing["status_updated_at"] = now
        claimed += 1

    write_json(path, ledger)
    schema = root / ".ai" / "guardrails" / "locked-job-search-data-model.json"
    errors = validate_file(path, schema, repo_root=root)
    if errors:
        print(f"ERROR: ledger validator failed for {path}:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    print(f"Claimed {claimed} pending tailor rows as in_progress on {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Claim pending tailor-queue rows as in_progress")
    parser.add_argument("--queue-file", required=True)
    parser.add_argument("--repo-root", default=None)
    args = parser.parse_args(argv)
    root = Path(args.repo_root).resolve() if args.repo_root else repo_root_from_here()
    queue_path = Path(args.queue_file)
    if not queue_path.is_absolute():
        queue_path = (root / queue_path).resolve()
    if not queue_path.is_file():
        print(f"ERROR: queue file missing: {queue_path}", file=sys.stderr)
        return 1
    return claim_file(root, queue_path, now=utc_now())


if __name__ == "__main__":
    raise SystemExit(main())
