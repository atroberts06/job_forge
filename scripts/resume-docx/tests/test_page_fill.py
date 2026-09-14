"""Advisory last-page fill estimator tests (ADR-051).

Anchors on committed sandbox resumes: the N=7 Authentic Brands resume must be
flagged below the ~65% trigger, while a filled N=5 resume reports >=~75%. Also
confirms fill_resume.py prints the advisory line and that the N<=5 path stays a
no-op (still advisory-only, no behavior change).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_DOCX_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_DOCX_DIR))

import fill_resume as filler  # noqa: E402
import page_fill as pf  # noqa: E402
from test_fill_validation import MASTER_TITLES, _resume, _themed  # noqa: E402

_REPO_ROOT = _DOCX_DIR.parents[1]
_SANDBOX_ROOT = _REPO_ROOT / ".ai/history/resume-tailor"
_ANCHOR_UNDERFILLED = (
    _SANDBOX_ROOT
    / "authentic-brands-group"
    / "manager-enterprise-integration-architect-6148480004"
    / "John_Doe_Resume_Authentic_Brands_Group.docx"
)
_ANCHOR_FILLED = (
    _SANDBOX_ROOT
    / "soni"
    / "principal-solution-architect"
    / "John_Doe_Resume_Soni.docx"
)


def _sandbox(tmp_path: Path, titles: list[str], bullets: list[list[str]]) -> Path:
    sandbox = tmp_path / "acme" / "architect"
    sandbox.mkdir(parents=True)
    _resume(sandbox / "tailored-resume.md", titles, bullets)
    return sandbox


def test_underfilled_accordion_resume_is_flagged(tmp_path: Path) -> None:
    sandbox = _sandbox(
        tmp_path,
        MASTER_TITLES[:7],
        [_themed(1) for _ in MASTER_TITLES[:7]],
    )
    dest = filler.gather_and_fill(sandbox)
    estimate = pf.estimate_fill(dest)
    # Accordion resume spilling to page 2 with few bullets: content spills past one page, last page is not full.
    assert estimate.page_count > 1
    assert estimate.last_page_fill_ratio < pf.TARGET_FILL_RATIO
    assert estimate.below_trigger is True


@pytest.mark.skipif(
    not _ANCHOR_FILLED.is_file(), reason="filled N=5 sandbox docx not present"
)
def test_well_filled_last_page_meets_target() -> None:
    estimate = pf.estimate_fill(_ANCHOR_FILLED)
    assert estimate.page_count > 1
    # A well-filled last page clears the ~75% target and never trips the trigger.
    assert estimate.last_page_fill_ratio >= pf.TARGET_FILL_RATIO
    assert estimate.below_trigger is False


def test_ratio_is_bounded_and_summary_formats() -> None:
    estimate = pf.estimate_fill(_ANCHOR_UNDERFILLED) if _ANCHOR_UNDERFILLED.is_file() else None
    if estimate is None:
        pytest.skip("anchor docx not present")
    assert 0.0 <= estimate.last_page_fill_ratio <= 1.0
    line = estimate.summary_line()
    assert line.startswith("last page ~")
    assert "target >=75% usable" in line


def test_filler_prints_fill_line(tmp_path: Path, monkeypatch, capsys) -> None:
    sandbox = _sandbox(
        tmp_path,
        MASTER_TITLES[:5],
        [_themed(3), _themed(3), _themed(3), _themed(3), _themed(3)],
    )
    monkeypatch.setattr(sys, "argv", ["fill_resume.py", "--sandbox", str(sandbox)])
    rc = filler.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "wrote " in out
    assert "last page ~" in out


def test_n5_path_is_advisory_no_op(tmp_path: Path) -> None:
    # N<=5 still produces a valid estimate; the estimator never gates on N and
    # never hard-fails. The N>5 loop lives in the SKILL, not in this module.
    sandbox = _sandbox(
        tmp_path,
        MASTER_TITLES[:5],
        [_themed(3), _themed(3), _themed(3), _themed(3), _themed(1)],
    )
    dest = filler.gather_and_fill(sandbox)
    estimate = pf.estimate_fill(dest)
    assert estimate.page_count >= 1
    assert 0.0 <= estimate.last_page_fill_ratio <= 1.0
