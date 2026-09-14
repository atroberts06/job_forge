"""Mint or overwrite queue-invoked P2-J1 job-description.md and job-id.txt.

Reads listing and analysis fields from a tailor-request queue row. Creates
the sandbox directory. Never reads job-id.txt to choose the intended id.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from upsert_engineering_log import find_row, load_json

REQUIRED_FIELDS = ("company", "title", "location", "url", "description_text")
NONE_BULLET = "- None"
MISMATCH_MESSAGE = "job-id.txt mismatch"


def intended_job_id(queue_doc: dict[str, Any], job_id: str | None) -> str:
    if job_id and str(job_id).strip():
        return str(job_id).strip()
    jobs = [
        row
        for row in (queue_doc.get("jobs") or [])
        if isinstance(row, dict) and row.get("id")
    ]
    if len(jobs) == 1:
        return str(jobs[0]["id"])
    raise ValueError("job id required: pass --job-id or use a one-job queue file")


def _require_text(row: dict[str, Any], key: str) -> str:
    value = str(row.get(key) or "").strip()
    if not value:
        raise ValueError(f"{key} is required")
    return value


def _unmet_lines(row: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for item in row.get("unmet_mandatory") or []:
        if not isinstance(item, dict):
            continue
        normalized = str(item.get("normalized") or "").strip()
        note = str(item.get("note") or "").strip()
        lines.append(f"- {normalized}: {note}")
    return lines or [NONE_BULLET]


def _skill_lines(row: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for item in row.get("mentioned_skills") or []:
        if not isinstance(item, dict):
            continue
        normalized = str(item.get("normalized") or "").strip()
        importance = str(item.get("importance") or "").strip()
        result = str(item.get("result") or "").strip()
        note = str(item.get("note") or "").strip()
        lines.append(f"- **{normalized}** (`{importance}`, `{result}`): {note}")
    return lines or [NONE_BULLET]


def render_job_description(row: dict[str, Any]) -> str:
    company = _require_text(row, "company")
    title = _require_text(row, "title")
    location = _require_text(row, "location")
    url = _require_text(row, "url")
    description_text = _require_text(row, "description_text")
    decision = str(row.get("decision") or "").strip()
    justification = str(row.get("justification") or "").strip()
    lines = [
        f"# {company} - {title}",
        "",
        f"- **Location:** {location}",
        f"- **URL:** {url}",
        "",
        "## Job description",
        "",
        description_text,
        "",
        "## Analysis summary",
        "",
        f"- **Decision:** {decision}",
        f"- **Justification:** {justification}",
        "",
        "## Unmet mandatory requirements",
        "",
        *_unmet_lines(row),
        "",
        "## Mentioned Skills",
        "",
        *_skill_lines(row),
        "",
    ]
    return "\n".join(lines)


def _assert_job_id_marker(sandbox: Path, intended: str) -> None:
    marker = sandbox / "job-id.txt"
    if not marker.is_file():
        return
    existing = marker.read_text(encoding="utf-8").strip()
    if existing != intended:
        raise ValueError(MISMATCH_MESSAGE)


def upsert_job_description(
    sandbox: Path,
    queue_path: Path,
    *,
    job_id: str | None = None,
) -> Path:
    if not queue_path.is_file():
        raise FileNotFoundError(f"queue file not found: {queue_path}")
    queue_doc = load_json(queue_path)
    if not isinstance(queue_doc, dict):
        raise ValueError("queue file root must be an object")
    intended = intended_job_id(queue_doc, job_id)
    row = find_row(queue_doc, intended)
    _assert_job_id_marker(sandbox, intended)
    for key in REQUIRED_FIELDS:
        _require_text(row, key)
    sandbox.mkdir(parents=True, exist_ok=True)
    dest = sandbox / "job-description.md"
    dest.write_text(render_job_description(row), encoding="utf-8", newline="\n")
    (sandbox / "job-id.txt").write_text(f"{intended}\n", encoding="utf-8", newline="\n")
    return dest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Upsert queue-invoked job-description.md from a tailor-request row."
    )
    parser.add_argument(
        "--sandbox",
        required=True,
        help="Path to .ai/history/resume-tailor/{company}/{position}",
    )
    parser.add_argument(
        "--queue-file",
        required=True,
        help="Path to .ai/history/resume-tailor/queue/{run_id}-tailor-request.json",
    )
    parser.add_argument(
        "--job-id",
        default=None,
        help="Queue row id. Optional when the queue has one job.",
    )
    args = parser.parse_args(argv)
    try:
        dest = upsert_job_description(
            Path(args.sandbox),
            Path(args.queue_file),
            job_id=args.job_id,
        )
    except (OSError, json.JSONDecodeError, KeyError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"wrote {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
