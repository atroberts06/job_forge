"""Mint or overwrite queue-invoked engineering-log.md sections 1-3.

Reads analysis fields from a tailor-request queue row, including optional
core_themes. Leaves research placeholders (Additional Company/Role
Expectations, Compensation Target) and section 4 for the resume-tailor agent.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RESEARCH_PLACEHOLDER = (
    "_[research placeholder — agent fills via WebSearch/WebFetch per "
    "resume_tailor_policy_001.research]_"
)
SECTION_4_PLACEHOLDER = (
    "_[placeholder — agent writes Core Modifications after research]_"
)
ACCOMPLISHMENT_PLACEHOLDER = (
    "Queue-invoked mint: after research, select locked-job-history.json "
    "accomplishments that evidence mentioned skills with result met or partial. "
    "Do not invent metrics. Write role-level mapping in section 4."
)
DECONFLICTION = (
    "All information in `.ai/guardrails/locked-resume-master-template.md` is "
    "source of truth and overrides conflicting facts, dates, skills, or "
    "accomplishments in locked-job-history.json or locked-skills.json."
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_job_id(sandbox: Path, queue_doc: dict[str, Any], job_id: str | None) -> str:
    if job_id:
        return job_id.strip()
    marker = sandbox / "job-id.txt"
    if marker.is_file():
        text = marker.read_text(encoding="utf-8").strip()
        if text:
            return text
    jobs = [row for row in (queue_doc.get("jobs") or []) if isinstance(row, dict) and row.get("id")]
    if len(jobs) == 1:
        return str(jobs[0]["id"])
    raise ValueError(
        "job id required: pass --job-id, write sandbox job-id.txt, or use a one-job queue file"
    )


def find_row(queue_doc: dict[str, Any], job_id: str) -> dict[str, Any]:
    for row in queue_doc.get("jobs") or []:
        if isinstance(row, dict) and str(row.get("id") or "") == job_id:
            return row
    raise KeyError(f"job_id {job_id!r} not found in queue file")


def _bullet_or_none(lines: list[str]) -> str:
    if not lines:
        return "- None listed on the queue row."
    return "\n".join(lines)


def _unmet_lines(row: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for item in row.get("unmet_mandatory") or []:
        if not isinstance(item, dict):
            continue
        normalized = str(item.get("normalized") or "").strip() or "(unnamed)"
        note = str(item.get("note") or "").strip()
        if note:
            lines.append(f"- **{normalized}:** {note}")
        else:
            lines.append(f"- **{normalized}**")
    return lines


def _skill_lines(row: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for item in row.get("mentioned_skills") or []:
        if not isinstance(item, dict):
            continue
        normalized = str(item.get("normalized") or "").strip() or "(unnamed)"
        importance = str(item.get("importance") or "").strip() or "unspecified"
        result = str(item.get("result") or "").strip() or "unspecified"
        note = str(item.get("note") or "").strip()
        suffix = f": {note}" if note else ""
        lines.append(f"- **{normalized}** (`{importance}`, `{result}`){suffix}")
    return lines


def _rank_key(item: dict[str, Any]) -> tuple[int, int, str]:
    importance = str(item.get("importance") or "")
    result = str(item.get("result") or "")
    imp_rank = 0 if importance == "mandatory" else 1 if importance == "preferred" else 2
    result_order = {"met": 0, "partial": 1, "not_evidenced": 2, "contradicted": 3}
    res_rank = result_order.get(result, 4)
    return (imp_rank, res_rank, str(item.get("normalized") or "").lower())


THEME_PLACEHOLDER = (
    "_[placeholder — queue row has no core_themes; agent uses locked skills "
    "and engineering-log research only]_"
)
CORE_THEME_FIELDS = (
    ("JOB_SKILL_1", "job_skill_1"),
    ("JOB_SKILL_2", "job_skill_2"),
    ("JOB_SKILL_3", "job_skill_3"),
    ("STRENGTH_1", "strength_1"),
    ("STRENGTH_2", "strength_2"),
    ("STRENGTH_3", "strength_3"),
    ("OPENING_HOOK", "opening_hook"),
)


def _theme_lines(row: dict[str, Any]) -> list[str]:
    themes = row.get("core_themes")
    if not isinstance(themes, dict) or not themes:
        return [f"- **{label}:** {THEME_PLACEHOLDER}" for label, _ in CORE_THEME_FIELDS]
    lines: list[str] = []
    for label, key in CORE_THEME_FIELDS:
        value = str(themes.get(key) or "").strip() or THEME_PLACEHOLDER
        lines.append(f"- **{label}:** {value}")
    return lines


def _ranked_skill_lines(row: dict[str, Any], results: set[str] | None = None) -> list[str]:
    skills = [item for item in (row.get("mentioned_skills") or []) if isinstance(item, dict)]
    if results is not None:
        skills = [item for item in skills if str(item.get("result") or "") in results]
    skills.sort(key=_rank_key)
    fake_row = {"mentioned_skills": skills}
    return _skill_lines(fake_row)


def render_log(row: dict[str, Any], *, timestamp: str) -> str:
    company = str(row.get("company") or "").strip() or "Unknown company"
    title = str(row.get("title") or "").strip() or "Unknown role"
    decision = str(row.get("decision") or "").strip() or "(missing)"
    justification = str(row.get("justification") or "").strip() or "(missing)"
    unmet = _unmet_lines(row)
    skills = _skill_lines(row)
    selected = _ranked_skill_lines(row, {"met", "partial"})
    all_skills = _ranked_skill_lines(row)
    return "\n".join(
        [
            f"# Engineering Log: {company} - {title}",
            f"Timestamp: {timestamp}",
            "",
            "## 1. Job Description Architecture Mapping",
            f"- **Key Themes Identified:** Queue analysis decision `{decision}`. {justification}",
            "- **Experience Requirements:** Derived from the queue-row analysis summary and unmet mandatory list. Agent does not re-derive qualification.",
            "- **Hard Technical Requirements:** Named skills from the queue-row `mentioned_skills` list:",
            _bullet_or_none(skills),
            f"- **Additional Company/Role Expectations Identified:** {RESEARCH_PLACEHOLDER}",
            f"- **Compensation Target:** {RESEARCH_PLACEHOLDER}",
            "",
            "## 2. Gap Analysis & Guardrail Compliance",
            "- **Experience Requirement Gap Analysis:** Unmet mandatory requirements from the queue row:",
            _bullet_or_none(unmet),
            "- **Technical Requirements Gap Analysis:** Mentioned skills from the queue row (do not invent locked skills or metrics):",
            _bullet_or_none(skills),
            f"- **Accomplishment Selection Strategy:** {ACCOMPLISHMENT_PLACEHOLDER}",
            f"- **Deconfliction Strategy:** {DECONFLICTION}",
            "",
            "## 3. Skill Selection & Ranking",
            "**Skill Selection** Mapped from queue-row `mentioned_skills`. Agent later uses `met`/`partial` in `tailored-resume.md` only when the name exists in locked-skills.json.",
            "**Skill Ranking** Mandatory before preferred. Then `met`, `partial`, `not_evidenced`, `contradicted`.",
            "### Selected Skills",
            "",
            _bullet_or_none(selected),
            "",
            "### All Skills",
            "",
            _bullet_or_none(all_skills),
            "",
            "### Core Strategic Themes & Alignment",
            "",
            _bullet_or_none(_theme_lines(row)),
            "",
            "## 4. Core Modifications Detail",
            SECTION_4_PLACEHOLDER,
            "",
        ]
    )


def upsert_engineering_log(
    sandbox: Path,
    queue_path: Path,
    *,
    job_id: str | None = None,
    timestamp: str | None = None,
) -> Path:
    if not sandbox.is_dir():
        raise FileNotFoundError(f"sandbox directory not found: {sandbox}")
    if not queue_path.is_file():
        raise FileNotFoundError(f"queue file not found: {queue_path}")
    queue_doc = load_json(queue_path)
    if not isinstance(queue_doc, dict):
        raise ValueError("queue file root must be an object")
    resolved = resolve_job_id(sandbox, queue_doc, job_id)
    row = find_row(queue_doc, resolved)
    dest = sandbox / "engineering-log.md"
    dest.write_text(
        render_log(row, timestamp=timestamp or utc_now_iso()),
        encoding="utf-8",
        newline="\n",
    )
    return dest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Upsert queue-invoked engineering-log.md from a tailor-request row."
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
        help="Queue row id. Optional when sandbox job-id.txt exists or the queue has one job.",
    )
    args = parser.parse_args(argv)
    try:
        dest = upsert_engineering_log(
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
