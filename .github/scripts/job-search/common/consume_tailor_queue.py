"""Consume tailor-request rows into approved-jobs.json (orchestrator-only).

- Drains completed rows from the queue file and updates the ledger status to completed.
- Failed rows are copied onto the ledger with status failed, but kept in the queue file.
- If all rows in the queue file are drained (none pending/failed), the queue file is deleted.
- If failed or pending rows remain, the queue file is updated in place and validated.
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

_RESUME_TAILOR = Path(__file__).resolve().parents[2] / "resume-tailor"
if str(_RESUME_TAILOR) not in sys.path:
    sys.path.insert(0, str(_RESUME_TAILOR))

from common.validate_job_search import load_json, repo_root_from_here, validate_file
from validate_tailor_request import validate_tailor_request

QUEUE_GLOB = "*-tailor-request.json"
TAILOR_COPY_KEYS = (
    "started_at",
    "attempt_count",
    "completed_at",
    "pr_url",
    "pr_number",
    "sandbox_path",
    "feature_branch",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def ledger_path(root: Path, platform: str) -> Path:
    return root / ".ai" / "history" / "job-search" / platform / "approved-jobs.json"


def upsert_row(jobs: list[dict[str, Any]], row: dict[str, Any]) -> None:
    job_id = row["id"]
    for index, existing in enumerate(jobs):
        if existing.get("id") == job_id:
            jobs[index] = row
            return
    jobs.append(row)


def queue_files(queue_dir: Path) -> list[Path]:
    files: list[tuple[int, Path]] = []
    if not queue_dir.is_dir():
        return []
    for path in queue_dir.glob(QUEUE_GLOB):
        if not path.is_file():
            continue
        try:
            doc = load_json(path)
        except (OSError, json.JSONDecodeError):
            files.append((10**9, path))
            continue
        batch = doc.get("batch_number")
        files.append((int(batch) if isinstance(batch, int) else 10**9, path))
    files.sort(key=lambda item: (item[0], item[1].name))
    return [p for _, p in files]


def consume_file(root: Path, queue_path: Path, *, now: str) -> int:
    queue = load_json(queue_path)
    platform = str(queue.get("platform") or "").strip()
    if not platform:
        print(f"ERROR: {queue_path}: platform is required", file=sys.stderr)
        return 1
    path = ledger_path(root, platform)
    if path.is_file():
        ledger = load_json(path)
    else:
        ledger = {"platform": platform, "jobs": []}
    jobs = ledger.setdefault("jobs", [])
    if not isinstance(jobs, list):
        print("ERROR: ledger jobs must be an array", file=sys.stderr)
        return 1

    copied = 0
    remaining: list[Any] = []
    for row in queue.get("jobs") or []:
        if not isinstance(row, dict):
            remaining.append(row)
            continue
        job_id = str(row.get("id") or "")
        status = row.get("status")
        existing = next((item for item in jobs if item.get("id") == job_id), None)
        if existing is None:
            print(f"ERROR: ledger row missing for {job_id}", file=sys.stderr)
            return 1
        updated = dict(existing)
        if status == "tailor_complete":
            updated["status"] = "completed"
            updated["status_updated_at"] = now
            for key in TAILOR_COPY_KEYS:
                updated[key] = row.get(key)
            updated.pop("failure", None)
            upsert_row(jobs, updated)
            copied += 1
        elif status == "failed":
            failure = row.get("failure")
            if not isinstance(failure, dict):
                print(f"ERROR: failed row {job_id} missing failure object", file=sys.stderr)
                return 1
            updated["status"] = "failed"
            updated["status_updated_at"] = now
            updated["failure"] = failure
            for key in TAILOR_COPY_KEYS:
                if key in row:
                    updated[key] = row[key]
            upsert_row(jobs, updated)
            copied += 1
            remaining.append(row)
        else:
            remaining.append(row)

    if remaining:
        queue["jobs"] = remaining
        write_json(queue_path, queue)
        errors = validate_tailor_request(queue_path)
        if errors:
            print(f"ERROR: queue validator failed for {queue_path}:", file=sys.stderr)
            for err in errors:
                print(f"  - {err}", file=sys.stderr)
            return 1
    else:
        queue_path.unlink(missing_ok=True)

    write_json(path, ledger)
    schema = root / ".ai" / "guardrails" / "locked-job-search-data-model.json"
    errors = validate_file(path, schema, repo_root=root)
    if errors:
        print(f"ERROR: ledger validator failed for {path}:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    print(f"Consumed {queue_path.name}; copied={copied} remaining_rows={len(remaining)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Consume tailor-request rows into approved-jobs.json")
    parser.add_argument("--queue-file", default=None)
    parser.add_argument("--repo-root", default=None)
    args = parser.parse_args(argv)
    root = Path(args.repo_root).resolve() if args.repo_root else repo_root_from_here()
    now = utc_now()
    if args.queue_file:
        queue_path = Path(args.queue_file)
        if not queue_path.is_absolute():
            queue_path = (root / queue_path).resolve()
        if not queue_path.is_file():
            print(f"ERROR: queue file missing: {queue_path}", file=sys.stderr)
            return 1
        paths = [queue_path]
    else:
        queue_dir = root / ".ai" / "history" / "resume-tailor" / "queue"
        paths = queue_files(queue_dir)
        if not paths:
            print("No tailor queue files.")
            return 0

    for queue_path in paths:
        code = consume_file(root, queue_path, now=now)
        if code != 0:
            return code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
