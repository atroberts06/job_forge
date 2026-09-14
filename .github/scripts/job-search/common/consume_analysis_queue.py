"""Consume analysis_complete queue rows into approved-jobs.json (P2-C1 / G6)."""

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

from common.validate_analysis_request import validate_analysis_request
from common.validate_job_search import encode_job_id, load_json, repo_root_from_here, validate_file

QUEUE_GLOB = "*-analysis-request.json"
POST_HANDOFF_STATUSES = frozenset({"in_progress", "failed", "completed", "deployed"})
RESUME_TAILOR_KEYS = (
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


def current_analysis(sidecar: dict[str, Any]) -> dict[str, Any] | None:
    for row in sidecar.get("analyses") or []:
        if isinstance(row, dict) and row.get("is_current") is True:
            return row
    return None


def incomplete_queue_files(queue_dir: Path) -> list[Path]:
    files: list[tuple[int, Path]] = []
    if not queue_dir.is_dir():
        return []
    for path in queue_dir.glob(QUEUE_GLOB):
        if not path.is_file():
            continue
        try:
            doc = load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        jobs = doc.get("jobs") or []
        if any(isinstance(j, dict) and j.get("status") == "analysis_complete" for j in jobs):
            batch = doc.get("batch_number")
            files.append((int(batch) if isinstance(batch, int) else 10**9, path))
    files.sort(key=lambda item: (item[0], item[1].name))
    return [p for _, p in files]


def ledger_path(root: Path, platform: str) -> Path:
    return root / ".ai" / "history" / "job-search" / platform / "approved-jobs.json"


def load_ledger(path: Path, platform: str) -> dict[str, Any]:
    if path.is_file():
        return load_json(path)
    return {"platform": platform, "jobs": []}


def parse_job_ids(raw: str | None) -> set[str] | None:
    if raw is None:
        return None
    return {part.strip() for part in raw.split(",") if part.strip()}


def platform_from_job_id(job_id: str) -> str | None:
    prefix = job_id.split(":", 1)[0].strip()
    return prefix or None


def persist_ledger(root: Path, ledger_file: Path, ledger: dict[str, Any]) -> int:
    write_json(ledger_file, ledger)
    schema = root / ".ai" / "guardrails" / "locked-job-search-data-model.json"
    ledger_errors = validate_file(ledger_file, schema, repo_root=root)
    if ledger_errors:
        print(f"ERROR: ledger validator failed for {ledger_file}:", file=sys.stderr)
        for err in ledger_errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    return 0


def sidecar_for(root: Path, platform: str, job_id: str) -> Path:
    return (
        root
        / ".ai"
        / "history"
        / "job-search"
        / platform
        / "analyses"
        / f"{encode_job_id(job_id)}-analysis.json"
    )


def load_current(root: Path, platform: str, job_id: str) -> dict[str, Any] | None:
    sidecar_path = sidecar_for(root, platform, job_id)
    if not sidecar_path.is_file():
        print(f"ERROR: sidecar missing for {job_id}", file=sys.stderr)
        return None
    sidecar = load_json(sidecar_path)
    current = current_analysis(sidecar)
    if current is None:
        print(f"ERROR: no is_current row for {job_id}", file=sys.stderr)
        return None
    return current


def consume_ids_from_sidecars(root: Path, job_ids: set[str], *, now: str) -> int:
    by_platform: dict[str, list[str]] = {}
    for job_id in sorted(job_ids):
        platform = platform_from_job_id(job_id)
        if platform is None:
            print(f"ERROR: malformed id {job_id}", file=sys.stderr)
            return 1
        by_platform.setdefault(platform, []).append(job_id)

    written = 0
    for platform, ids in by_platform.items():
        ledger_file = ledger_path(root, platform)
        ledger = load_ledger(ledger_file, platform)
        for job_id in ids:
            current = load_current(root, platform, job_id)
            if current is None:
                return 1
            apply_g6(
                ledger,
                job_id,
                current.get("analysis_id"),
                str(current.get("decision") or ""),
                now,
                allow_post_handoff=True,
            )
            print(
                f"Retargeted {platform}/approved-jobs.json id={job_id} "
                f"analysis_id={current.get('analysis_id')} decision={current.get('decision')}"
            )
            written += 1
        if persist_ledger(root, ledger_file, ledger) != 0:
            return 1
    print(f"Sidecar consume: {written}")
    return 0


def first_fill_row(job_id: str, analysis_id: Any, now: str) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": job_id,
        "analysis_id": analysis_id,
        "approved_at": now,
        "status": "approved",
        "status_updated_at": now,
    }
    for key in RESUME_TAILOR_KEYS:
        row[key] = None
    return row


def heal_resume_keys(row: dict[str, Any]) -> None:
    for key in RESUME_TAILOR_KEYS:
        if key not in row:
            row[key] = None


def apply_g6(
    ledger: dict[str, Any],
    job_id: str,
    analysis_id: Any,
    decision: str,
    now: str,
    *,
    allow_post_handoff: bool = False,
) -> None:
    jobs = ledger.setdefault("jobs", [])
    if not isinstance(jobs, list):
        ledger["jobs"] = []
        jobs = ledger["jobs"]
    index = next((i for i, row in enumerate(jobs) if isinstance(row, dict) and row.get("id") == job_id), None)
    if decision == "rejected":
        if index is None:
            return
        status = jobs[index].get("status")
        if allow_post_handoff or status not in POST_HANDOFF_STATUSES:
            jobs.pop(index)
        return
    if decision != "approved":
        return
    if index is None:
        jobs.append(first_fill_row(job_id, analysis_id, now))
        return
    row = jobs[index]
    row["id"] = job_id
    row["analysis_id"] = analysis_id
    row["approved_at"] = now
    row["status"] = "approved"
    row["status_updated_at"] = now
    heal_resume_keys(row)


def consume_file(
    root: Path,
    queue_path: Path,
    *,
    now: str,
    overwrite_ids: set[str] | None = None,
) -> int:
    queue = load_json(queue_path)
    platform = str(queue.get("platform") or "").strip()
    if not platform:
        print(f"ERROR: {queue_path}: platform is required", file=sys.stderr)
        return 1
    jobs = queue.get("jobs")
    if not isinstance(jobs, list):
        print(f"ERROR: {queue_path}: jobs must be an array", file=sys.stderr)
        return 1

    ledger_file = ledger_path(root, platform)
    ledger = load_ledger(ledger_file, platform)
    remaining: list[Any] = []

    for row in jobs:
        if not isinstance(row, dict) or row.get("status") != "analysis_complete":
            remaining.append(row)
            continue
        job_id = str(row.get("id") or "")
        current = load_current(root, platform, job_id)
        if current is None:
            return 1
        apply_g6(
            ledger,
            job_id,
            current.get("analysis_id"),
            str(current.get("decision") or ""),
            now,
            allow_post_handoff=overwrite_ids is not None and job_id in overwrite_ids,
        )

    if remaining:
        queue["jobs"] = remaining
        write_json(queue_path, queue)
        errors = validate_analysis_request(queue_path)
        if errors:
            print(f"ERROR: queue validator failed for {queue_path}:", file=sys.stderr)
            for err in errors:
                print(f"  - {err}", file=sys.stderr)
            return 1
    else:
        queue_path.unlink(missing_ok=True)

    if persist_ledger(root, ledger_file, ledger) != 0:
        return 1
    print(f"Consumed {queue_path.name}; remaining_rows={len(remaining)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Consume analysis_complete rows into approved-jobs.json")
    parser.add_argument("--queue-file", default=None)
    parser.add_argument("--repo-root", default=None)
    parser.add_argument(
        "--job-id",
        default=None,
        help="One id or comma-separated ids. Overwrites matching ledger rows even when post-handoff. Without --queue-file, retargets from the current sidecar (no queue required). Omit for batch (status protection stays on).",
    )
    args = parser.parse_args(argv)

    root = Path(args.repo_root).resolve() if args.repo_root else repo_root_from_here()
    queue_dir = root / ".ai" / "history" / "job-search" / "queue"

    overwrite_ids = parse_job_ids(args.job_id)
    if args.job_id is not None and not overwrite_ids:
        print("ERROR: --job-id requires at least one id.", file=sys.stderr)
        return 1

    if args.queue_file:
        queue_path = Path(args.queue_file)
        if not queue_path.is_absolute():
            queue_path = (root / queue_path).resolve()
        if not queue_path.is_file():
            print(f"ERROR: queue file missing: {queue_path}", file=sys.stderr)
            return 1
        return consume_file(root, queue_path, now=utc_now(), overwrite_ids=overwrite_ids)

    if overwrite_ids is not None:
        return consume_ids_from_sidecars(root, overwrite_ids, now=utc_now())

    files = incomplete_queue_files(queue_dir)
    if not files:
        print("No incomplete analysis queue files.")
        return 0
    return consume_file(root, files[0], now=utc_now(), overwrite_ids=None)


if __name__ == "__main__":
    raise SystemExit(main())
