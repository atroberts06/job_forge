"""Cover letter fill aborts on missing sections, nested tokens, and contact gaps."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_DOCX_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_DOCX_DIR))

import fill_cover_letter as filler

from test_fill_cover_letter import _sandbox


def test_missing_section_aborts(tmp_path: Path) -> None:
    sandbox = _sandbox(tmp_path)
    path = sandbox / "tailored-cover-letter.md"
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("## Opener", "## Hook"), encoding="utf-8")
    with pytest.raises(filler.FillError, match="missing required section"):
        filler.gather_and_fill(sandbox)


def test_unresolved_nested_token_aborts(tmp_path: Path) -> None:
    sandbox = _sandbox(tmp_path)
    path = sandbox / "tailored-cover-letter.md"
    text = path.read_text(encoding="utf-8")
    path.write_text(
        text.replace(
            "I have honed Salesforce Education Cloud",
            "I have honed {{JOB_SKILL_1}}",
        ),
        encoding="utf-8",
    )
    with pytest.raises(filler.FillError, match="unresolved nested token"):
        filler.gather_and_fill(sandbox)


def test_missing_contact_email_aborts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sandbox = _sandbox(tmp_path)
    contact_path = tmp_path / "locked-contact.json"
    payload = json.loads(filler.CONTACT_PATH.read_text(encoding="utf-8"))
    payload["email"] = ""
    contact_path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(filler, "CONTACT_PATH", contact_path)
    locked = dict(filler.REQUIRED_LOCKED)
    locked["contact"] = contact_path
    monkeypatch.setattr(filler, "REQUIRED_LOCKED", locked)
    with pytest.raises(filler.FillError, match="email"):
        filler.gather_and_fill(sandbox)


def test_missing_cover_letter_markdown_aborts(tmp_path: Path) -> None:
    sandbox = _sandbox(tmp_path)
    (sandbox / "tailored-cover-letter.md").unlink()
    with pytest.raises(filler.FillError, match="missing required file"):
        filler.gather_and_fill(sandbox)
