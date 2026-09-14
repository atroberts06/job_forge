#!/usr/bin/env python3
"""Build resume-tailor manifest and stage deploy artifacts for CD pipeline."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (
    REQUIRED_RESUME_TAILOR_FILES,
    SANDBOX_COVER_LETTER_DOCX_GLOB,
    SANDBOX_DOCX_GLOB,
    changed_resume_tailor_dirs,
    resume_tailor_identity,
)

RESUME_FILENAME = "tailored-resume.md"
ENGINEERING_LOG_FILENAME = "engineering-log.md"
OUTREACH_FILENAME = "tailored-outreach.md"


def stage_file(resume_tailor_dir: Path, filename: str, output_path: Path) -> None:
    source = resume_tailor_dir / filename
    if not source.is_file():
        raise FileNotFoundError(f"Missing {filename} in {resume_tailor_dir}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, output_path)


def build_manifest_entry(resume_tailor_dir: Path, commit_sha: str) -> dict:
    company_name, role_title = resume_tailor_identity(resume_tailor_dir)
    files = [
        name
        for name in REQUIRED_RESUME_TAILOR_FILES
        if (resume_tailor_dir / name).is_file()
    ]
    prefix = f"{company_name}-{role_title}"
    docx_matches = sorted(resume_tailor_dir.glob(SANDBOX_DOCX_GLOB))
    docx_name = docx_matches[0].name if docx_matches else None
    cover_letter_matches = sorted(resume_tailor_dir.glob(SANDBOX_COVER_LETTER_DOCX_GLOB))
    cover_letter_docx_name = cover_letter_matches[0].name if cover_letter_matches else None
    return {
        "company_name": company_name,
        "role_title": role_title,
        "branch_slug": f"feature/{company_name}-{role_title}",
        "resume_tailor_directory": str(resume_tailor_dir).replace("\\", "/"),
        "drive_folder": f"{company_name}/{role_title}",
        "files": files,
        "resume_artifact": f"dist/resume-tailor/{prefix}-{RESUME_FILENAME}",
        "engineering_log_artifact": (
            f"dist/resume-tailor/{prefix}-{ENGINEERING_LOG_FILENAME}"
        ),
        "outreach_artifact": (
            f"dist/resume-tailor/{prefix}-{OUTREACH_FILENAME}"
        ),
        "resume_docx_artifact": (
            f"dist/resume-tailor/{prefix}-{docx_name}" if docx_name else None
        ),
        "resume_docx_name": docx_name,
        "cover_letter_docx_artifact": (
            f"dist/resume-tailor/{prefix}-{cover_letter_docx_name}"
            if cover_letter_docx_name
            else None
        ),
        "cover_letter_docx_name": cover_letter_docx_name,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build resume-tailor manifest and stage deploy artifacts."
    )
    parser.add_argument("--base", default="HEAD~1", help="Git base ref (default: HEAD~1)")
    parser.add_argument("--head", default="HEAD", help="Git head ref (default: HEAD)")
    parser.add_argument("--commit-sha", default="", help="Commit SHA for manifest metadata")
    parser.add_argument("--output-dir", default="dist", help="Output directory (default: dist)")
    args = parser.parse_args()

    resume_tailor_dirs = changed_resume_tailor_dirs(args.base, args.head)
    output_dir = Path(args.output_dir)
    resume_tailor_out = output_dir / "resume-tailor"
    resume_tailor_out.mkdir(parents=True, exist_ok=True)

    if not resume_tailor_dirs:
        manifest = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "commit_sha": args.commit_sha,
            "resume_tailor": [],
        }
        manifest_path = output_dir / "resume-tailor-manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print("No resume-tailor changes detected — empty manifest written.")
        return 0

    entries = []
    for resume_tailor_dir in resume_tailor_dirs:
        entry = build_manifest_entry(resume_tailor_dir, args.commit_sha)
        try:
            for filename, artifact_key in (
                (RESUME_FILENAME, "resume_artifact"),
                (ENGINEERING_LOG_FILENAME, "engineering_log_artifact"),
                (OUTREACH_FILENAME, "outreach_artifact"),
            ):
                staged_path = resume_tailor_out / Path(entry[artifact_key]).name
                stage_file(resume_tailor_dir, filename, staged_path)
                entry[artifact_key] = str(staged_path).replace("\\", "/")
                print(f"  staged {resume_tailor_dir / filename} -> {staged_path}")
            docx_name = entry.get("resume_docx_name")
            if not docx_name:
                print(
                    f"ERROR: missing {SANDBOX_DOCX_GLOB} in {resume_tailor_dir}",
                    file=sys.stderr,
                )
                return 1
            staged_docx = resume_tailor_out / Path(entry["resume_docx_artifact"]).name
            stage_file(resume_tailor_dir, docx_name, staged_docx)
            entry["resume_docx_artifact"] = str(staged_docx).replace("\\", "/")
            print(f"  staged {resume_tailor_dir / docx_name} -> {staged_docx}")
            cover_letter_docx_name = entry.get("cover_letter_docx_name")
            if not cover_letter_docx_name:
                print(
                    f"ERROR: missing {SANDBOX_COVER_LETTER_DOCX_GLOB} in {resume_tailor_dir}",
                    file=sys.stderr,
                )
                return 1
            staged_cover = resume_tailor_out / Path(entry["cover_letter_docx_artifact"]).name
            stage_file(resume_tailor_dir, cover_letter_docx_name, staged_cover)
            entry["cover_letter_docx_artifact"] = str(staged_cover).replace("\\", "/")
            print(
                f"  staged {resume_tailor_dir / cover_letter_docx_name} -> {staged_cover}"
            )
        except FileNotFoundError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        entries.append(entry)

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "commit_sha": args.commit_sha,
        "resume_tailor": entries,
    }
    manifest_path = output_dir / "resume-tailor-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Manifest written to {manifest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
