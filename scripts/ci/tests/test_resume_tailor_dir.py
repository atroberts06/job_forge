"""resume_tailor_dir_from_path sandbox vs reserved queue/ paths."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_CI_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_CI_DIR))

from common import RESUME_TAILOR_ROOT, resume_tailor_dir_from_path


@pytest.mark.parametrize(
    "changed, expected",
    [
        (".ai/history/resume-tailor/queue/.gitkeep", None),
        (
            ".ai/history/resume-tailor/queue/c1d2e3f4a5b6789012345678abcdef01-tailor-request.json",
            None,
        ),
        (".ai/history/resume-tailor/queue/nested/ignored.md", None),
        (".ai/history/resume-tailor/acme/.gitkeep", None),
        (".ai/history/resume-tailor/acme/readme.md", None),
        (".ai/history/resume-tailor/Deloitte/tailored-resume.md", None),
        (".ai/history/job-search/queue/run-analysis-request.json", None),
        (
            ".ai/history/resume-tailor/acme/architect/job-description.md",
            RESUME_TAILOR_ROOT / "acme" / "architect",
        ),
        (
            ".ai\\history\\resume-tailor\\volkswagen-group\\solution-architect\\engineering-log.md",
            RESUME_TAILOR_ROOT / "volkswagen-group" / "solution-architect",
        ),
    ],
)
def test_resume_tailor_dir_from_path(changed: str, expected: Path | None) -> None:
    assert resume_tailor_dir_from_path(changed) == expected
