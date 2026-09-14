"""Shared fixtures for job-search offline tests."""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pytest

JOB_SEARCH_DIR = Path(__file__).resolve().parent
COMMON_DIR = JOB_SEARCH_DIR / "common"
SCRIPTS_DIR = COMMON_DIR
if str(JOB_SEARCH_DIR) not in sys.path:
    sys.path.insert(0, str(JOB_SEARCH_DIR))

FIXTURES = COMMON_DIR / "tests" / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def criteria() -> dict:
    data = json.loads((FIXTURES / "criteria.json").read_text(encoding="utf-8"))
    rows = data.get("criteria") if isinstance(data, dict) else None
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict) and row.get("id") == "jsc_001":
                return row
    return data


@pytest.fixture
def schema_path(tmp_path: Path) -> Path:
    """Copy locked schema into tmp if available; else use fixture schema."""
    repo_schema = JOB_SEARCH_DIR.parents[2] / ".ai" / "guardrails" / "locked-job-search-data-model.json"
    if repo_schema.is_file():
        return repo_schema
    return FIXTURES / "data_model.json"


def make_job(
    *,
    job_id: str = "greenhouse:lts:100",
    source_job_id: str = "100",
    status: str = "new",
    title: str = "Solution Architect",
    company: str = "LTS",
    location: str = "New York, NY",
    work_location_type: str = "unknown",
    url: str = "https://job-boards.greenhouse.io/lts/jobs/100",
    pulled_at: str = "2026-08-11",
    posted_at: str | None = None,
    status_updated_at: str = "2026-08-11T15:00:00Z",
    description_text: str = "Architect role",
) -> dict:
    return {
        "id": job_id,
        "source_job_id": source_job_id,
        "status": status,
        "title": title,
        "company": company,
        "location": location,
        "work_location_type": work_location_type,
        "url": url,
        "pulled_at": pulled_at,
        "posted_at": posted_at,
        "status_updated_at": status_updated_at,
        "description_text": description_text,
    }


def make_envelope(
    jobs: list[dict],
    *,
    pulled_at: str = "2026-08-11T15:00:00Z",
    platform: str = "greenhouse",
) -> dict:
    return {
        "platform": platform,
        "pulled_at": pulled_at,
        "jobs": jobs,
    }


def make_raw_greenhouse(
    *,
    job_id: int = 100,
    title: str = "Solution Architect",
    location_name: str = "New York, NY",
    offices: list[dict] | None = None,
    metadata: list | dict | None = None,
    absolute_url: str | None = None,
    content: str = "<p>Architect role</p>",
) -> dict:
    raw: dict = {
        "id": job_id,
        "title": title,
        "absolute_url": absolute_url or f"https://job-boards.greenhouse.io/lts/jobs/{job_id}",
        "location": {"name": location_name},
        "offices": offices if offices is not None else [],
        "content": content,
    }
    if metadata is not None:
        raw["metadata"] = metadata
    return raw


def make_company_row(
    *,
    company_id: str = "lts",
    name: str = "LTS",
    company_url: str = "https://lts.com/",
    industries: list | None = None,
    ats_enabled: bool = True,
    ats_platform: str = "greenhouse",
    ats_token: str = "lts",
    ats_career_url: str | None = None,
    company_enabled: bool = False,
    company_career_url: str | None = None,
) -> dict:
    if ats_career_url is None:
        if ats_platform == "greenhouse":
            ats_career_url = f"https://job-boards.greenhouse.io/{ats_token}"
        elif ats_platform == "lever":
            ats_career_url = f"https://jobs.lever.co/{ats_token}"
        elif ats_platform == "ashby":
            ats_career_url = f"https://jobs.ashbyhq.com/{ats_token}"
        else:
            ats_career_url = f"https://{ats_platform}.example/{ats_token}" if ats_platform else ""
    if company_career_url is None:
        company_career_url = f"https://{company_id}.com"
    return {
        "id": company_id,
        "name": name,
        "company_url": company_url,
        "industries": list(industries) if industries is not None else [],
        "ats": {
            "enabled": ats_enabled,
            "platform": ats_platform,
            "board_token": ats_token,
            "career_url": ats_career_url,
            "source": "manual",
            "detected_at": None,
        },
        "company": {
            "enabled": company_enabled,
            "platform": company_id,
            "board_token": company_id,
            "career_url": company_career_url,
            "source": "manual",
            "detected_at": None,
        },
    }


def make_companies_catalog(rows: list[dict] | None = None) -> dict:
    return {"companies": list(rows) if rows is not None else [make_company_row()]}


def write_day(
    src_root: Path,
    day: date | str,
    jobs: list[dict],
    pulled_at: str | None = None,
    *,
    platform: str = "greenhouse",
) -> Path:
    day_str = day.isoformat() if isinstance(day, date) else day
    out_dir = src_root / day_str
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "jobs.json"
    ts = pulled_at or f"{day_str}T12:00:00Z"
    out_path.write_text(
        json.dumps(make_envelope(jobs, pulled_at=ts, platform=platform), indent=2) + "\n",
        encoding="utf-8",
    )
    return out_path


@pytest.fixture
def repo_layout(tmp_path: Path, criteria: dict, schema_path: Path) -> dict:
    """Minimal repo tree for fetch_greenhouse_jobs.main offline runs."""
    root = tmp_path / "repo"
    job_search = root / ".ai" / "history" / "job-search"
    platform = job_search / "greenhouse"
    src = platform / "src"
    src.mkdir(parents=True)
    (job_search / "companies.json").write_text(
        json.dumps(make_companies_catalog(), indent=2) + "\n",
        encoding="utf-8",
    )

    guardrails = root / ".ai" / "guardrails"
    guardrails.mkdir(parents=True)
    if isinstance(criteria.get("criteria"), list):
        criteria_payload = criteria
    else:
        row = dict(criteria)
        row.setdefault("id", "jsc_001")
        row.setdefault("pipeline", "greenhouse")
        row.setdefault("created_on", "2026-08-06T00:00:00Z")
        row.setdefault("modified_on", "2026-08-11T00:00:00Z")
        row.setdefault("description", "test criteria")
        criteria_payload = {"criteria": [row]}
    (guardrails / "locked-job-search-criteria.json").write_text(
        json.dumps(criteria_payload), encoding="utf-8"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    (guardrails / "locked-job-search-data-model.json").write_text(
        json.dumps(schema), encoding="utf-8"
    )
    return {"root": root, "src": src, "platform": platform, "job_search": job_search}
