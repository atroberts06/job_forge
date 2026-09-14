"""companies.json schema + Greenhouse ats pull selection."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from conftest import make_company_row, make_companies_catalog, make_raw_greenhouse
from greenhouse.fetch_greenhouse_jobs import main
from common.validate_job_search import (
    company_enabled_boards,
    greenhouse_ats_boards,
    validate_companies_semantic,
    validate_file,
)


def _write_catalog(repo_layout: dict, catalog: dict) -> None:
    path = repo_layout["job_search"] / "companies.json"
    path.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")


def test_seed_catalog_validates(schema_path: Path):
    repo = Path(__file__).resolve().parents[5]
    path = repo / ".ai" / "history" / "job-search" / "companies.json"
    assert path.is_file()
    assert validate_file(path, schema_path) == []


def test_company_enabled_boards_reads_enabled_company_slot():
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
            make_company_row(company_enabled=False),
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


def test_greenhouse_ats_boards_ignores_company_slot_and_disabled_ats():
    catalog = make_companies_catalog(
        [
            make_company_row(company_enabled=True),
            make_company_row(
                company_id="acme",
                name="Acme",
                ats_enabled=False,
                ats_token="acme",
                ats_career_url="https://job-boards.greenhouse.io/acme",
            ),
        ]
    )
    boards = greenhouse_ats_boards(catalog)
    assert boards == [{"board_token": "lts", "company": "LTS"}]


def test_greenhouse_ats_boards_skips_non_greenhouse_platform():
    catalog = make_companies_catalog(
        [make_company_row(ats_platform="lever", ats_token="lts")]
    )
    assert greenhouse_ats_boards(catalog) == []


def test_duplicate_id_fails_semantic():
    catalog = make_companies_catalog(
        [make_company_row(), make_company_row(name="LTS 2")]
    )
    errors = validate_companies_semantic(catalog)
    assert any("duplicate id" in e for e in errors)


def test_duplicate_platform_token_fails_semantic():
    catalog = make_companies_catalog(
        [
            make_company_row(),
            make_company_row(
                company_id="other",
                name="Other",
                ats_token="lts",
            ),
        ]
    )
    errors = validate_companies_semantic(catalog)
    assert any("duplicate (platform, board_token)" in e for e in errors)


def test_company_slot_identity_mismatch_fails():
    row = make_company_row()
    row["company"]["platform"] = "nope"
    errors = validate_companies_semantic(make_companies_catalog([row]))
    assert any("slot=company" in e and "must equal parent id" in e for e in errors)


def test_ats_career_url_must_contain_platform_and_token():
    row = make_company_row(ats_career_url="https://www.indeed.com/viewjob?jk=1")
    errors = validate_companies_semantic(make_companies_catalog([row]))
    assert any("slot=ats" in e and "career_url" in e for e in errors)


def test_company_career_url_must_contain_company_name():
    row = make_company_row(company_career_url="https://jooble.org")
    errors = validate_companies_semantic(make_companies_catalog([row]))
    assert any("slot=company" in e and "career_url" in e for e in errors)


def test_company_career_url_must_be_origin():
    row = make_company_row(company_career_url="https://lts.com/careers")
    errors = validate_companies_semantic(make_companies_catalog([row]))
    assert any("origin" in e and "slot=company" in e for e in errors)


def test_fetch_ignores_enabled_company_slot(repo_layout):
    _write_catalog(
        repo_layout,
        make_companies_catalog([make_company_row(company_enabled=True)]),
    )
    raw = [make_raw_greenhouse(job_id=100, location_name="New York, NY")]
    with (
        patch("greenhouse.fetch_greenhouse_jobs.utc_today") as today,
        patch("greenhouse.fetch_greenhouse_jobs.fetch_board_jobs", return_value=raw) as fetch,
        patch("greenhouse.fetch_greenhouse_jobs.now_iso", return_value="2026-08-11T16:00:00Z"),
        patch("common.clock.now_iso", return_value="2026-08-11T16:00:00Z"),
    ):
        from datetime import date

        today.return_value = date(2026, 8, 11)
        rc = main(["--repo-root", str(repo_layout["root"]), "--date", "2026-08-11"])
    assert rc == 0
    fetch.assert_called_once_with("lts")


def test_fetch_skips_disabled_ats(repo_layout):
    _write_catalog(
        repo_layout,
        make_companies_catalog([make_company_row(ats_enabled=False)]),
    )
    with (
        patch("greenhouse.fetch_greenhouse_jobs.utc_today") as today,
        patch("greenhouse.fetch_greenhouse_jobs.fetch_board_jobs") as fetch,
        patch("greenhouse.fetch_greenhouse_jobs.now_iso", return_value="2026-08-11T16:00:00Z"),
    ):
        from datetime import date

        today.return_value = date(2026, 8, 11)
        rc = main(["--repo-root", str(repo_layout["root"]), "--date", "2026-08-11"])
    assert rc == 1
    fetch.assert_not_called()


def test_fetch_fails_zero_pullable_boards(repo_layout):
    _write_catalog(repo_layout, {"companies": []})
    with (
        patch("greenhouse.fetch_greenhouse_jobs.utc_today") as today,
        patch("greenhouse.fetch_greenhouse_jobs.fetch_board_jobs") as fetch,
    ):
        from datetime import date

        today.return_value = date(2026, 8, 11)
        rc = main(["--repo-root", str(repo_layout["root"]), "--date", "2026-08-11"])
    assert rc == 1
    fetch.assert_not_called()


def test_fetch_fails_duplicate_token(repo_layout):
    _write_catalog(
        repo_layout,
        make_companies_catalog(
            [
                make_company_row(),
                make_company_row(company_id="other", name="Other", ats_token="lts"),
            ]
        ),
    )
    with (
        patch("greenhouse.fetch_greenhouse_jobs.utc_today") as today,
        patch("greenhouse.fetch_greenhouse_jobs.fetch_board_jobs") as fetch,
    ):
        from datetime import date

        today.return_value = date(2026, 8, 11)
        rc = main(["--repo-root", str(repo_layout["root"]), "--date", "2026-08-11"])
    assert rc == 1
    fetch.assert_not_called()
