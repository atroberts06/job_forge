"""Mint tailor-request queue files from approved-jobs.json + listing + sidecar.

Discovers every job-search sandbox with src/ (inline; no shared helper).
Writes one queue file family per platform. Never mixes platforms in one file.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

SCRIPTS_JOB_SEARCH = Path(__file__).resolve().parents[1] / "job-search"
if str(SCRIPTS_JOB_SEARCH) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_JOB_SEARCH))

from common.agent_policy import RESUME_TAILOR_POLICY_ID, load_agent_policy  # noqa: E402
from common.validate_job_search import encode_job_id, load_json, repo_root_from_here  # noqa: E402

from validate_tailor_request import validate_tailor_request  # noqa: E402


def _load_tailor_queue_slugs():
    ci_common = Path(__file__).resolve().parents[3] / "scripts" / "ci" / "common.py"
    spec = importlib.util.spec_from_file_location("ci_common", ci_common)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load CI common helpers from {ci_common}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.tailor_queue_slugs


tailor_queue_slugs = _load_tailor_queue_slugs()

QUEUE_GLOB = "*-tailor-request.json"
SKIP_SANDBOX_NAMES = frozenset({"queue", "dashboard"})
SKIP_STATUSES = {"in_progress", "completed", "failed", "deployed"}


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


def mint_run_id() -> str:
    return uuid.uuid4().hex


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


def current_analysis(sidecar: dict[str, Any]) -> dict[str, Any] | None:
    for row in sidecar.get("analyses") or []:
        if isinstance(row, dict) and row.get("is_current") is True:
            return row
    return None


def unmet_mandatory(current: dict[str, Any]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for section_name in ("experience", "skills", "constraints"):
        section = current.get(section_name) or {}
        for req in section.get("requirements") or []:
            if not isinstance(req, dict):
                continue
            if req.get("importance") == "mandatory" and req.get("result") in {
                "not_evidenced",
                "contradicted",
            }:
                items.append(
                    {
                        "normalized": str(req.get("normalized") or ""),
                        "note": str(req.get("note") or ""),
                    }
                )
    return items


def mentioned_skills(current: dict[str, Any]) -> list[dict[str, Any]]:
    skills = (current.get("skills") or {}).get("requirements") or []
    copied: list[dict[str, Any]] = []
    for req in skills:
        if not isinstance(req, dict):
            continue
        copied.append(
            {
                "jd_excerpt": req.get("jd_excerpt"),
                "normalized": req.get("normalized"),
                "source_section": req.get("source_section"),
                "importance": req.get("importance"),
                "result": req.get("result"),
                "evidence": req.get("evidence"),
                "note": req.get("note"),
            }
        )
    return copied


def existing_queue_files(queue_dir: Path) -> list[Path]:
    if not queue_dir.is_dir():
        return []
    return sorted(p for p in queue_dir.glob(QUEUE_GLOB) if p.is_file())


def write_batch(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def mint_job_row(
    job_id: str,
    listing: dict[str, Any],
    current: dict[str, Any],
    ledger_row: dict[str, Any],
) -> dict[str, Any]:
    source_job_id = str(listing.get("source_job_id") or "").strip()
    company_slug, position_slug = tailor_queue_slugs(
        str(listing.get("company") or ""),
        str(listing.get("title") or ""),
        source_job_id,
    )
    row = {
        "id": job_id,
        "status": "pending",
        "company": listing.get("company"),
        "title": listing.get("title"),
        "company_slug": company_slug,
        "position_slug": position_slug,
        "location": listing.get("location"),
        "url": listing.get("url"),
        "description_text": listing.get("description_text"),
        "decision": current.get("decision"),
        "justification": current.get("justification"),
        "unmet_mandatory": unmet_mandatory(current),
        "mentioned_skills": mentioned_skills(current),
        "started_at": None,
        "attempt_count": ledger_row.get("attempt_count", None),
        "completed_at": None,
        "pr_url": ledger_row.get("pr_url", None),
        "pr_number": ledger_row.get("pr_number", None),
        "sandbox_path": ledger_row.get("sandbox_path", None),
        "feature_branch": ledger_row.get("feature_branch", None),
    }
    themes = current.get("core_themes")
    if isinstance(themes, dict):
        row["core_themes"] = themes
    return row


def collect_approved(
    *,
    platform_root: Path,
    requested: set[str] | None,
) -> list[dict[str, Any]] | None:
    ledger_file = platform_root / "approved-jobs.json"
    if not ledger_file.is_file():
        return []
    ledger = load_json(ledger_file)
    index = dated_jobs_index(platform_root / "src")
    analyses_dir = platform_root / "analyses"
    selected: list[dict[str, Any]] = []

    for row in ledger.get("jobs") or []:
        if not isinstance(row, dict):
            continue
        job_id = str(row.get("id") or "")
        if requested is not None and job_id not in requested:
            continue
        if row.get("status") != "approved":
            continue
        if row.get("status") in SKIP_STATUSES:
            continue
        listing = last_seen_row(index, job_id)
        if listing is None:
            print(f"ERROR: no last-seen listing for {job_id}", file=sys.stderr)
            return None
        sidecar_path = analyses_dir / f"{encode_job_id(job_id)}-analysis.json"
        if not sidecar_path.is_file():
            print(f"ERROR: sidecar missing for {job_id}", file=sys.stderr)
            return None
        sidecar = load_json(sidecar_path)
        current = current_analysis(sidecar)
        if current is None:
            print(f"ERROR: no is_current analysis for {job_id}", file=sys.stderr)
            return None
        try:
            selected.append(mint_job_row(job_id, listing, current, row))
        except ValueError as exc:
            print(f"ERROR: cannot mint slugs for {job_id}: {exc}", file=sys.stderr)
            return None
    return selected


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate tailor-request queue files")
    parser.add_argument("--repo-root", default=None)
    parser.add_argument(
        "--platform",
        action="append",
        default=None,
        help="Limit discovery (comma list or repeatable). Default: all sandboxes with src/.",
    )
    parser.add_argument(
        "--job-id",
        default=None,
        help="One id or comma-separated ids. Mints only matching status: approved ledger rows.",
    )
    args = parser.parse_args(argv)

    root = Path(args.repo_root).resolve() if args.repo_root else repo_root_from_here()
    job_search = root / ".ai" / "history" / "job-search"
    queue_dir = root / ".ai" / "history" / "resume-tailor" / "queue"

    existing = existing_queue_files(queue_dir)
    if existing:
        names = ", ".join(p.name for p in existing)
        print(f"ERROR: tailor queue is not empty ({names}). Clear queue files first.", file=sys.stderr)
        return 1

    try:
        policy = load_agent_policy(root, RESUME_TAILOR_POLICY_ID)
        max_jobs = int(policy["execution"]["max_jobs_per_agent"])
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        print(f"ERROR: cannot read tailor policy: {exc}", file=sys.stderr)
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

    requested: set[str] | None = None
    if args.job_id:
        requested = {part.strip() for part in args.job_id.split(",") if part.strip()}
        allowed = set(platforms)
        filtered: set[str] = set()
        for job_id in requested:
            prefix = platform_from_job_id(job_id)
            if prefix is None or prefix not in discovered or prefix not in allowed:
                continue
            filtered.add(job_id)
        requested = filtered
        platforms = [
            name
            for name in platforms
            if any(platform_from_job_id(job_id) == name for job_id in requested)
        ]

    per_platform: list[tuple[str, list[dict[str, Any]]]] = []
    for platform in platforms:
        selected = collect_approved(
            platform_root=job_search / platform,
            requested=requested,
        )
        if selected is None:
            return 1
        if selected:
            per_platform.append((platform, selected))

    if not per_platform:
        print("Nothing was eligible.")
        return 0

    created_date = utc_today().isoformat()
    written = 0
    for platform, selected in per_platform:
        for batch_number, offset in enumerate(range(0, len(selected), max_jobs), start=1):
            chunk = selected[offset : offset + max_jobs]
            run_id = mint_run_id()
            payload = {
                "run_id": run_id,
                "batch_number": batch_number,
                "platform": platform,
                "created_date": created_date,
                "jobs": chunk,
            }
            dest = queue_dir / f"{run_id}-tailor-request.json"
            write_batch(dest, payload)
            errors = validate_tailor_request(dest)
            if errors:
                print(f"ERROR: queue validator failed for {dest}:", file=sys.stderr)
                for err in errors:
                    print(f"  - {err}", file=sys.stderr)
                return 1
            written += 1
            print(f"Wrote {dest} platform={platform} jobs={len(chunk)} batch_number={batch_number}")

    print(f"Queue files: {written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
