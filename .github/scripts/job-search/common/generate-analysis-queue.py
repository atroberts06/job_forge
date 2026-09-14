"""Mint analysis-request queue files from committed sidecars and dated jobs.json.

Discovers every job-search sandbox with src/ (inline; no shared helper).
Writes one queue file family per platform. Never mixes platforms in one file.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

_JOB_SEARCH = Path(__file__).resolve().parents[1]
if str(_JOB_SEARCH) not in sys.path:
    sys.path.insert(0, str(_JOB_SEARCH))

from common.agent_policy import JOB_ANALYSIS_POLICY_ID, load_agent_policy
from common.validate_analysis_request import validate_analysis_request
from common.validate_job_search import encode_job_id, load_json, repo_root_from_here

QUEUE_GLOB = "*-analysis-request.json"
SKIP_SANDBOX_NAMES = frozenset({"queue", "dashboard"})
LISTING_KEYS = (
    "company",
    "title",
    "location",
    "work_location_type",
    "url",
    "description_text",
)
WORK_LOCATION_TYPES = frozenset({"remote", "hybrid", "onsite", "unknown"})


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


def mint_run_id() -> str:
    return uuid.uuid4().hex


def load_policy(root: Path) -> dict[str, Any]:
    return load_agent_policy(root, JOB_ANALYSIS_POLICY_ID)


def discover_platforms(job_search: Path) -> list[str]:
    """Sandboxes under job-search that have src/. Skip queue, dashboard, files."""
    if not job_search.is_dir():
        return []
    found: list[str] = []
    for child in sorted(p for p in job_search.iterdir() if p.is_dir()):
        if child.name in SKIP_SANDBOX_NAMES:
            continue
        if (child / "src").is_dir():
            found.append(child.name)
    return found


def parse_platform_args(raw: list[str] | None) -> list[str] | None:
    if raw is None:
        return None
    names: list[str] = []
    seen: set[str] = set()
    for item in raw:
        for part in str(item).split(","):
            name = part.strip()
            if not name or name in seen:
                continue
            seen.add(name)
            names.append(name)
    return names


def platform_from_job_id(job_id: str) -> str | None:
    prefix = job_id.split(":", 1)[0].strip()
    return prefix or None


def dated_jobs_index(src_root: Path) -> dict[str, list[tuple[str, dict[str, Any]]]]:
    """job_id -> list of (date, row) for every dated jobs.json, newest last."""
    index: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    if not src_root.is_dir():
        return index
    dates = sorted(p.name for p in src_root.iterdir() if p.is_dir() and p.name[:4].isdigit())
    for day in dates:
        jobs_path = src_root / day / "jobs.json"
        if not jobs_path.is_file():
            continue
        try:
            data = load_json(jobs_path)
        except (OSError, json.JSONDecodeError):
            continue
        for job in data.get("jobs") or []:
            if not isinstance(job, dict) or not job.get("id"):
                continue
            index.setdefault(str(job["id"]), []).append((day, job))
    return index


def last_seen_row(
    index: dict[str, list[tuple[str, dict[str, Any]]]], job_id: str
) -> dict[str, Any] | None:
    rows = index.get(job_id)
    if not rows:
        return None
    return rows[-1][1]


def current_revision(sidecar: dict[str, Any]) -> int | None:
    for row in sidecar.get("analyses") or []:
        if isinstance(row, dict) and row.get("is_current") is True:
            rev = row.get("revision")
            return int(rev) if isinstance(rev, int) else None
    return None


def existing_queue_files(queue_dir: Path) -> list[Path]:
    if not queue_dir.is_dir():
        return []
    return sorted(p for p in queue_dir.glob(QUEUE_GLOB) if p.is_file())


def write_batch(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def sidecar_ids(analyses_dir: Path) -> list[str]:
    ids: list[str] = []
    if not analyses_dir.is_dir():
        return ids
    for path in sorted(analyses_dir.glob("*-analysis.json")):
        try:
            doc = load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        job_id = str(doc.get("job_id") or "")
        if job_id:
            ids.append(job_id)
    return ids


def mint_job_row(job_id: str, listing: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": job_id,
        "status": "pending",
        "company": listing.get("company"),
        "title": listing.get("title"),
        "location": listing.get("location"),
        "work_location_type": listing.get("work_location_type"),
        "url": listing.get("url"),
        "description_text": listing.get("description_text"),
    }


def select_jobs(
    *,
    analyses_dir: Path,
    index: dict[str, list[tuple[str, dict[str, Any]]]],
    candidates: list[str],
    require_revision_0: bool,
) -> tuple[list[dict[str, Any]], list[str]]:
    selected: list[dict[str, Any]] = []
    skipped: list[str] = []
    for job_id in candidates:
        sidecar_path = analyses_dir / f"{encode_job_id(job_id)}-analysis.json"
        if not sidecar_path.is_file():
            skipped.append(job_id)
            print(f"SKIP {job_id}: no sidecar", file=sys.stderr)
            continue
        try:
            sidecar = load_json(sidecar_path)
        except (OSError, json.JSONDecodeError):
            skipped.append(job_id)
            print(f"SKIP {job_id}: malformed sidecar", file=sys.stderr)
            continue
        row = last_seen_row(index, job_id)
        if row is None or row.get("status") == "closed":
            skipped.append(job_id)
            print(f"SKIP {job_id}: last-seen missing or closed", file=sys.stderr)
            continue
        if row.get("status") not in ("new", "active"):
            skipped.append(job_id)
            print(f"SKIP {job_id}: last-seen status {row.get('status')!r}", file=sys.stderr)
            continue
        if require_revision_0:
            rev = current_revision(sidecar)
            if rev != 0:
                continue
        missing_or_blank = [
            k for k in LISTING_KEYS if not isinstance(row.get(k), str) or not str(row.get(k) or "").strip()
        ]
        if missing_or_blank:
            skipped.append(job_id)
            print(f"SKIP {job_id}: missing or blank listing field(s): {', '.join(missing_or_blank)}", file=sys.stderr)
            continue
        if row.get("work_location_type") not in WORK_LOCATION_TYPES:
            skipped.append(job_id)
            print(f"SKIP {job_id}: invalid work_location_type {row.get('work_location_type')!r}", file=sys.stderr)
            continue
        selected.append(mint_job_row(job_id, row))
    return selected, skipped


def write_platform_batches(
    *,
    queue_dir: Path,
    platform: str,
    selected: list[dict[str, Any]],
    max_jobs: int,
    created_date: str,
    invoke: str,
) -> int | None:
    written = 0
    for batch_number, offset in enumerate(range(0, len(selected), max_jobs), start=1):
        chunk = selected[offset : offset + max_jobs]
        run_id = mint_run_id()
        payload = {
            "run_id": run_id,
            "batch_number": batch_number,
            "platform": platform,
            "created_date": created_date,
            "invoke": invoke,
            "jobs": chunk,
        }
        dest = queue_dir / f"{run_id}-analysis-request.json"
        write_batch(dest, payload)
        errors = validate_analysis_request(dest)
        if errors:
            print(f"ERROR: queue validator failed for {dest}:", file=sys.stderr)
            for err in errors:
                print(f"  - {err}", file=sys.stderr)
            return None
        written += 1
        print(f"Wrote {dest} platform={platform} jobs={len(chunk)} batch_number={batch_number}")
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate analysis-request queue files")
    parser.add_argument("--repo-root", default=None)
    parser.add_argument(
        "--job-id",
        default=None,
        help="One id or comma-separated ids. Queues stubs and already-filled ids together.",
    )
    parser.add_argument(
        "--platform",
        action="append",
        default=None,
        help="Limit discovery (comma list or repeatable). Default: all sandboxes with src/.",
    )
    parser.add_argument(
        "--invoke",
        choices=("manual", "batch"),
        default="batch",
        help="Queue envelope invoke. Default batch, independent of --job-id. Orchestrator never passes this flag.",
    )
    args = parser.parse_args(argv)

    root = Path(args.repo_root).resolve() if args.repo_root else repo_root_from_here()
    job_search = root / ".ai" / "history" / "job-search"
    queue_dir = job_search / "queue"

    existing = existing_queue_files(queue_dir)
    if existing:
        names = ", ".join(p.name for p in existing)
        print(f"ERROR: queue/ is not empty ({names}). Clear queue files first.", file=sys.stderr)
        return 1

    try:
        policy = load_policy(root)
        max_jobs = int(policy["execution"]["max_jobs_per_agent"])
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        print(f"ERROR: cannot read analysis policy: {exc}", file=sys.stderr)
        return 1

    discovered = discover_platforms(job_search)
    wanted = parse_platform_args(args.platform)
    if args.platform is not None and not wanted:
        print("ERROR: --platform requires at least one platform name.", file=sys.stderr)
        return 1
    if wanted is not None:
        unknown = [name for name in wanted if name not in discovered]
        if unknown:
            print(
                f"ERROR: --platform not discovered (need src/): {', '.join(unknown)}",
                file=sys.stderr,
            )
            return 1
        platforms = [name for name in discovered if name in set(wanted)]
    else:
        platforms = discovered

    requested: list[str] | None = None
    if args.job_id:
        requested = [part.strip() for part in args.job_id.split(",") if part.strip()]

    jobs_by_platform: dict[str, list[str]] | None = None
    skipped: list[str] = []
    if requested is not None:
        jobs_by_platform = {name: [] for name in platforms}
        allowed = set(platforms)
        for job_id in requested:
            prefix = platform_from_job_id(job_id)
            if prefix is None:
                skipped.append(job_id)
                print(f"SKIP {job_id}: malformed id", file=sys.stderr)
                continue
            if prefix not in discovered:
                skipped.append(job_id)
                print(f"SKIP {job_id}: platform {prefix!r} not discovered", file=sys.stderr)
                continue
            if prefix not in allowed:
                skipped.append(job_id)
                print(f"SKIP {job_id}: platform {prefix!r} excluded by --platform", file=sys.stderr)
                continue
            jobs_by_platform.setdefault(prefix, []).append(job_id)
        platforms = [name for name in platforms if jobs_by_platform.get(name)]

    created_date = utc_today().isoformat()
    written = 0
    any_selected = False

    for platform in platforms:
        platform_root = job_search / platform
        analyses_dir = platform_root / "analyses"
        index = dated_jobs_index(platform_root / "src")
        if jobs_by_platform is None:
            candidates = sidecar_ids(analyses_dir)
            require_revision_0 = True
        else:
            candidates = jobs_by_platform.get(platform) or []
            require_revision_0 = False
        selected, skip_more = select_jobs(
            analyses_dir=analyses_dir,
            index=index,
            candidates=candidates,
            require_revision_0=require_revision_0,
        )
        skipped.extend(skip_more)
        if not selected:
            continue
        any_selected = True
        count = write_platform_batches(
            queue_dir=queue_dir,
            platform=platform,
            selected=selected,
            max_jobs=max_jobs,
            created_date=created_date,
            invoke=args.invoke,
        )
        if count is None:
            return 1
        written += count

    if requested is not None and not any_selected:
        print("Every --job-id was skipped.")
        return 0
    if requested is None and not any_selected:
        print("Nothing was eligible.")
        return 0

    print(f"Queue files: {written}")
    if skipped:
        print(f"Skipped: {len(skipped)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
