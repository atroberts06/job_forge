#!/usr/bin/env python3
"""Syntax-check immutable JSON guardrail and ADR files."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

GUARDRAIL_JSON_FILES = (
    Path(".ai/guardrails/locked-job-history.json"),
    Path(".ai/guardrails/locked-skills.json"),
    Path(".ai/guardrails/locked-contact.json"),
    Path(".ai/guardrails/locked-education.json"),
    Path(".ai/guardrails/locked-professional-summary.json"),
    Path(".ai/guardrails/locked-job-search-criteria.json"),
    Path(".ai/guardrails/locked-job-search-data-model.json"),
    Path(".ai/guardrails/locked-job-data-model.json"),
    Path(".ai/guardrails/locked-agent-policies.json"),
    Path(".ai/guardrails/locked-certifications.json"),
    Path(".ai/guardrails/locked-clearance.json"),
    Path(".ai/guardrails/locked-licenses.json"),
    Path(".ai/guardrails/locked-projects.json"),
    Path(".ai/history/architectural-decisions/architectural-decision-log.json"),
    Path(".ai/history/architectural-decisions/resume-data-model.json"),
    Path(".ai/history/architectural-decisions/cover-letter-data-model.json"),
)
LOCKED_RESUME_TEMPLATE = Path(".ai/guardrails/locked-resume-template.docx")
LOCKED_COVER_LETTER_TEMPLATE = Path(".ai/guardrails/locked-cover-letter-template.docx")
LOCKED_COVER_LETTER_MASTER = Path(".ai/guardrails/locked-cover-letter-template.md")


def validate_json_file(path: Path) -> str | None:
    if not path.is_file():
        return f"missing file: {path}"
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return f"{path}: invalid JSON — {exc}"
    return None


def main() -> int:
    errors: list[str] = []
    for path in GUARDRAIL_JSON_FILES:
        error = validate_json_file(path)
        if error:
            errors.append(error)
        else:
            print(f"  OK: {path}")

    if not LOCKED_RESUME_TEMPLATE.is_file():
        errors.append(f"missing file: {LOCKED_RESUME_TEMPLATE}")
    else:
        print(f"  OK: {LOCKED_RESUME_TEMPLATE}")

    for path in (LOCKED_COVER_LETTER_TEMPLATE, LOCKED_COVER_LETTER_MASTER):
        if not path.is_file():
            errors.append(f"missing file: {path}")
        else:
            print(f"  OK: {path}")

    if errors:
        print("\nGuardrail JSON validation FAILED:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print("Guardrail JSON validation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
