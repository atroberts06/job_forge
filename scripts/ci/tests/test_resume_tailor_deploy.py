"""Resume-tailor deploy manifest and Google Drive upload coverage."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_CI_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_CI_DIR))

import build_resume_tailor_manifest as manifest_builder
from common import REQUIRED_RESUME_TAILOR_FILES
from sync_gdrive import artifact_uploads


def _sandbox(tmp_path: Path, *, include_outreach: bool = True) -> Path:
    sandbox = (
        tmp_path
        / ".ai"
        / "history"
        / "resume-tailor"
        / "acme"
        / "enterprise-architect"
    )
    sandbox.mkdir(parents=True)
    for filename in REQUIRED_RESUME_TAILOR_FILES:
        if filename == "tailored-outreach.md" and not include_outreach:
            continue
        (sandbox / filename).write_text(f"{filename}\n", encoding="utf-8")
    (sandbox / "John_Doe_Resume_Acme.docx").write_bytes(b"docx")
    (sandbox / "John_Doe_Cover_Letter_Acme.docx").write_bytes(b"docx")
    return sandbox


def _run_builder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, sandbox: Path
) -> int:
    relative_sandbox = sandbox.relative_to(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        manifest_builder,
        "changed_resume_tailor_dirs",
        lambda _base, _head: [relative_sandbox],
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "build_resume_tailor_manifest.py",
            "--base",
            "base",
            "--head",
            "head",
            "--commit-sha",
            "abc123",
        ],
    )
    return manifest_builder.main()


def test_builder_stages_outreach_and_records_manifest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sandbox = _sandbox(tmp_path)

    assert _run_builder(monkeypatch, tmp_path, sandbox) == 0

    manifest = json.loads(
        (tmp_path / "dist" / "resume-tailor-manifest.json").read_text(
            encoding="utf-8"
        )
    )
    entry = manifest["resume_tailor"][0]
    outreach = Path(entry["outreach_artifact"])
    assert outreach.as_posix() == (
        "dist/resume-tailor/"
        "acme-enterprise-architect-tailored-outreach.md"
    )
    assert (tmp_path / outreach).read_text(encoding="utf-8") == (
        "tailored-outreach.md\n"
    )
    assert "cover_letter_artifact" not in entry
    cover_docx = Path(entry["cover_letter_docx_artifact"])
    assert cover_docx.as_posix() == (
        "dist/resume-tailor/"
        "acme-enterprise-architect-John_Doe_Cover_Letter_Acme.docx"
    )
    assert entry["cover_letter_docx_name"] == "John_Doe_Cover_Letter_Acme.docx"
    assert (tmp_path / cover_docx).read_bytes() == b"docx"


def test_builder_fails_when_outreach_is_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sandbox = _sandbox(tmp_path, include_outreach=False)

    assert _run_builder(monkeypatch, tmp_path, sandbox) == 1


def test_builder_fails_when_cover_letter_docx_is_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sandbox = _sandbox(tmp_path)
    (sandbox / "John_Doe_Cover_Letter_Acme.docx").unlink()

    assert _run_builder(monkeypatch, tmp_path, sandbox) == 1


def test_drive_uploads_include_outreach_with_stable_name() -> None:
    entry = {
        "resume_artifact": "dist/resume.md",
        "engineering_log_artifact": "dist/log.md",
        "outreach_artifact": "dist/outreach.md",
        "resume_docx_artifact": "dist/resume.docx",
        "resume_docx_name": "John_Doe_Resume_Acme.docx",
        "cover_letter_docx_artifact": "dist/cover.docx",
        "cover_letter_docx_name": "John_Doe_Cover_Letter_Acme.docx",
    }

    uploads = artifact_uploads(entry)
    assert ("dist/outreach.md", "tailored-outreach.md") in uploads
    assert not any(
        name == "tailored-cover-letter.md" for _, name in uploads
    )
    assert (
        "dist/cover.docx",
        "John_Doe_Cover_Letter_Acme.docx",
    ) in uploads
