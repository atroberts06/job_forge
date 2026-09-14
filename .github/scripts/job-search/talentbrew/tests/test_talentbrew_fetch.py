"""Offline TalentBrew fetch: mocked HTTP, criteria, envelope write."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

from conftest import make_company_row, make_companies_catalog
from talentbrew.fetch_talentbrew_jobs import company_enabled_boards, main

FIXTURES = Path(__file__).resolve().parent / "fixtures"
REPO_SCHEMA = Path(__file__).resolve().parents[5] / ".ai" / "guardrails" / "locked-job-search-data-model.json"
TODAY = date(2026, 9, 6)


def _jsc_003(**overrides) -> dict:
    row = {
        "id": "jsc_003",
        "pipeline": "talentbrew",
        "created_on": "2026-09-05T00:00:00Z",
        "modified_on": "2026-09-05T00:00:00Z",
        "description": "test",
        "records_per_page": 100,
        "search_keywords": None,
        "search_location": None,
        "search_type": 5,
        "sort_criteria": 0,
        "sort_direction": 0,
        "distance": 50,
        "radius_unit_type": 0,
        "active_facet_id": 0,
        "show_radius": False,
        "timeout_seconds": 60,
        "request_delay_ms": 0,
        "max_retries": 0,
        "retry_status_codes": [429, 503],
        "max_pages": 2,
        "facets": {
            "teams": None,
            "country": None,
            "state": None,
            "locations": None,
            "divisions": None,
            "students_and_grads": None,
            "remote": None,
            "sponsorship": None,
            "role_type": None,
            "vanity_tag": None,
        },
        "titles": {
            "include": ["architect", "analyst", "engineer", "team lead"],
            "exclude": ["intern"],
        },
        "locations": {"include": ["NJ", "New Jersey", "New York", "NY", "NYC"]},
        "work_location_type": {
            "include_remote": True,
            "include_hybrid": True,
            "include_onsite": True,
        },
    }
    row.update(overrides)
    return row


def _write_repo(tmp_path: Path, *, criteria: dict | None = None) -> Path:
    root = tmp_path / "repo"
    job_search = root / ".ai" / "history" / "job-search"
    (job_search / "talentbrew" / "src").mkdir(parents=True)
    catalog = make_companies_catalog(
        [
            make_company_row(
                company_id="capital-one",
                name="Capital One",
                ats_enabled=False,
                ats_platform="",
                ats_token="",
                company_enabled=True,
                company_career_url="https://www.capitalonecareers.com",
            )
        ]
    )
    catalog["companies"][0]["ats"] = {
        "enabled": False,
        "platform": "",
        "board_token": "",
        "career_url": "",
        "source": "",
        "detected_at": None,
    }
    catalog["companies"][0]["company"]["source"] = "manual"
    catalog["companies"][0]["company"]["detected_at"] = "2026-09-06"
    (job_search / "companies.json").write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
    guardrails = root / ".ai" / "guardrails"
    guardrails.mkdir(parents=True)
    payload = {
        "criteria": [
            {"id": "jsc_001", "pipeline": "greenhouse"},
            criteria or _jsc_003(),
        ]
    }
    (guardrails / "locked-job-search-criteria.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    (guardrails / "locked-job-search-data-model.json").write_text(
        REPO_SCHEMA.read_text(encoding="utf-8"), encoding="utf-8"
    )
    return root


class _Http:
    def __init__(self) -> None:
        self.urls: list[str] = []
        self.list_html = (FIXTURES / "list_results_mixed.html").read_text(encoding="utf-8")
        self.filters = (FIXTURES / "filters_sample.html").read_text(encoding="utf-8")
        self.keep_detail = (FIXTURES / "detail_keep.html").read_bytes()
        self.sample_detail = (FIXTURES / "detail_sample.html").read_bytes()

    def __call__(self, url: str, **_kwargs):
        self.urls.append(url)
        if "/search-jobs/results" in url:
            if "CurrentPage=2" in url or "CurrentPage=2&" in url:
                return 200, json.dumps({"filters": "", "results": "", "hasJobs": False}).encode()
            return 200, json.dumps(
                {"filters": self.filters, "results": self.list_html, "hasJobs": True}
            ).encode()
        if url.endswith("/11111111111"):
            return 200, self.keep_detail
        if url.endswith("/96262041488"):
            return 200, self.sample_detail
        raise AssertionError(f"unexpected url {url}")


def test_company_enabled_boards_reads_company_slot():
    catalog = make_companies_catalog(
        [
            make_company_row(
                company_id="capital-one",
                name="Capital One",
                ats_enabled=False,
                ats_platform="",
                ats_token="",
                company_enabled=True,
                company_career_url="https://www.capitalonecareers.com",
            ),
            make_company_row(
                company_id="other",
                name="Other",
                ats_enabled=False,
                ats_platform="",
                ats_token="",
                company_enabled=False,
                company_career_url="https://other.example",
            ),
        ]
    )
    boards = company_enabled_boards(catalog)
    assert boards == [
        {
            "board_token": "capital-one",
            "company": "Capital One",
            "career_url": "https://www.capitalonecareers.com",
        }
    ]


def test_fetch_keeps_ny_engineer_drops_mclean_and_intern(tmp_path):
    root = _write_repo(tmp_path)
    http = _Http()
    with (
        patch("talentbrew.fetch_talentbrew_jobs.http_get", http),
        patch("talentbrew.fetch_talentbrew_jobs.utc_today", return_value=TODAY),
        patch("talentbrew.fetch_talentbrew_jobs.now_iso", return_value="2026-09-06T13:23:51Z"),
    ):
        assert main(["--repo-root", str(root), "--date", "2026-09-06"]) == 0
    jobs_path = root / ".ai" / "history" / "job-search" / "talentbrew" / "src" / "2026-09-06" / "jobs.json"
    envelope = json.loads(jobs_path.read_text(encoding="utf-8"))
    assert envelope["platform"] == "talentbrew"
    ids = [job["id"] for job in envelope["jobs"]]
    assert ids == ["talentbrew:capital-one:11111111111"]
    assert envelope["jobs"][0]["workday_requisition_id"] == "R111111"
    detail_urls = [url for url in http.urls if "/job/" in url]
    assert any(url.endswith("/11111111111") for url in detail_urls)
    assert not any(url.endswith("/22222222222") for url in detail_urls)


def test_unknown_facet_label_fails_closed(tmp_path):
    root = _write_repo(tmp_path, criteria=_jsc_003(facets={"teams": ["Not A Real Team"]}))
    http = _Http()
    with (
        patch("talentbrew.fetch_talentbrew_jobs.http_get", http),
        patch("talentbrew.fetch_talentbrew_jobs.utc_today", return_value=TODAY),
        patch("talentbrew.fetch_talentbrew_jobs.now_iso", return_value="2026-09-06T13:23:51Z"),
    ):
        assert main(["--repo-root", str(root), "--date", "2026-09-06"]) == 1
