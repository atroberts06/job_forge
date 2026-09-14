#!/usr/bin/env python3
"""Validate resume-tailor artifact presence and resume chronology (ADR-006 CI v1)."""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (
    MASTER_RESUME,
    PLACEHOLDER_TOKEN,
    REQUIRED_RESUME_TAILOR_FILES,
    SANDBOX_COVER_LETTER_DOCX_GLOB,
    SANDBOX_DOCX_GLOB,
    changed_resume_tailor_dirs,
    excluded_resume_role_titles,
    parse_role_headers,
    unresolved_docx_placeholders,
    validate_printed_role_prefix,
)


def validate_resume_tailor_dir(resume_tailor_dir) -> list[str]:
    errors: list[str] = []
    for filename in REQUIRED_RESUME_TAILOR_FILES:
        if not (resume_tailor_dir / filename).is_file():
            errors.append(f"{resume_tailor_dir}: missing required file '{filename}'")

    tailored = resume_tailor_dir / "tailored-resume.md"
    if tailored.is_file() and MASTER_RESUME.is_file():
        master_headers = parse_role_headers(MASTER_RESUME)
        tailored_headers = parse_role_headers(tailored)
        prefix_error = validate_printed_role_prefix(
            master_headers,
            tailored_headers,
            excluded_resume_role_titles(),
        )
        if prefix_error:
            errors.append(f"{resume_tailor_dir}: {prefix_error}")

    docx_matches = sorted(resume_tailor_dir.glob(SANDBOX_DOCX_GLOB))
    if not docx_matches:
        errors.append(
            f"{resume_tailor_dir}: missing required file matching '{SANDBOX_DOCX_GLOB}'"
        )
    else:
        for docx_path in docx_matches:
            try:
                leftover_parts = unresolved_docx_placeholders(docx_path)
            except (OSError, zipfile.BadZipFile, UnicodeDecodeError) as exc:
                errors.append(f"{docx_path}: unable to read — {exc}")
                continue
            if leftover_parts:
                errors.append(
                    f"{docx_path}: leftover template placeholder "
                    f"'{PLACEHOLDER_TOKEN}' in {', '.join(leftover_parts)}"
                )

    cover_letter_matches = sorted(resume_tailor_dir.glob(SANDBOX_COVER_LETTER_DOCX_GLOB))
    if not cover_letter_matches:
        errors.append(
            f"{resume_tailor_dir}: missing required file matching "
            f"'{SANDBOX_COVER_LETTER_DOCX_GLOB}'"
        )
    else:
        for docx_path in cover_letter_matches:
            try:
                leftover_parts = unresolved_docx_placeholders(docx_path)
            except (OSError, zipfile.BadZipFile, UnicodeDecodeError) as exc:
                errors.append(f"{docx_path}: unable to read — {exc}")
                continue
            if leftover_parts:
                errors.append(
                    f"{docx_path}: leftover template placeholder "
                    f"'{PLACEHOLDER_TOKEN}' in {', '.join(leftover_parts)}"
                )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate resume-tailor artifacts and chronology."
    )
    parser.add_argument(
        "--base",
        default="origin/main",
        help="Git base ref for change detection (default: origin/main)",
    )
    parser.add_argument(
        "--head",
        default="HEAD",
        help="Git head ref for change detection (default: HEAD)",
    )
    args = parser.parse_args()

    resume_tailor_dirs = changed_resume_tailor_dirs(args.base, args.head)
    if not resume_tailor_dirs:
        print(
            "No resume-tailor directory changes detected — skipping resume-tailor validation."
        )
        return 0

    print(
        f"Validating {len(resume_tailor_dirs)} changed resume-tailor director(y/ies)..."
    )
    all_errors: list[str] = []
    for resume_tailor_dir in resume_tailor_dirs:
        print(f"  checking {resume_tailor_dir}")
        all_errors.extend(validate_resume_tailor_dir(resume_tailor_dir))

    if all_errors:
        print("\nResume-tailor validation FAILED:", file=sys.stderr)
        for error in all_errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print("Resume-tailor validation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
