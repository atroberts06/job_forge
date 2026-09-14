"""Shared fixtures for resume-tailor queue tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
JOB_SEARCH = SCRIPTS_DIR.parent / "job-search"
FIXTURES = Path(__file__).resolve().parent / "fixtures"

for path in (SCRIPTS_DIR, JOB_SEARCH):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def repo_layout(tmp_path: Path) -> dict:
    root = tmp_path / "repo"
    platform = root / ".ai" / "history" / "job-search" / "greenhouse"
    src = platform / "src"
    src.mkdir(parents=True)
    catalog = {
        "companies": [
            {
                "id": "lts",
                "name": "LTS",
                "company_url": "https://lts.com/",
                "industries": [],
                "ats": {
                    "enabled": True,
                    "platform": "greenhouse",
                    "board_token": "lts",
                    "career_url": "https://job-boards.greenhouse.io/lts",
                    "source": "manual",
                    "detected_at": None,
                },
                "company": {
                    "enabled": False,
                    "platform": "lts",
                    "board_token": "lts",
                    "career_url": "https://lts.com",
                    "source": "manual",
                    "detected_at": None,
                },
            }
        ]
    }
    (platform.parent / "companies.json").write_text(
        json.dumps(catalog, indent=2) + "\n", encoding="utf-8"
    )
    repo_schema = JOB_SEARCH.parents[2] / ".ai" / "guardrails" / "locked-job-search-data-model.json"
    guardrails = root / ".ai" / "guardrails"
    guardrails.mkdir(parents=True)
    if repo_schema.is_file():
        (guardrails / "locked-job-search-data-model.json").write_text(
            repo_schema.read_text(encoding="utf-8"), encoding="utf-8"
        )
    return {"root": root, "src": src, "platform": platform}
