"""Unit tests for Greenhouse board token discovery, Inertia parsing, reachability probe, and catalog normalization."""

from __future__ import annotations

import io
import json
import sqlite3
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from common.validate_job_search import validate_companies_semantic, validate_file
from conftest import make_companies_catalog, make_company_row
from greenhouse.chrome_cookie import (
    decrypt_cookie_value,
    extract_greenhouse_cookies,
    get_my_greenhouse_session_cookie,
)
from greenhouse.discover_greenhouse_boards import (
    build_search_queries,
    deduplicate_against_catalog,
    extract_board_token,
    extract_inertia_version_from_html,
    fetch_inertia_version,
    insert_new_companies,
    kebab_case,
    load_discovery_criteria,
    main,
    parse_inertia_jobs_payload,
    probe_board_reachability,
    query_my_greenhouse_inertia,
    run_discovery,
)


def test_kebab_case_formatting():
    assert kebab_case("Acme Corporation, Inc.") == "acme-corporation-inc"
    assert kebab_case("  Stripe  ") == "stripe"
    assert kebab_case("94-1687665 Bank of America") == "94-1687665-bank-of-america"
    assert kebab_case("LTS") == "lts"


def test_extract_board_token_url_variants():
    # Direct modern URL
    assert extract_board_token("https://job-boards.greenhouse.io/stripe/jobs/12345") == "stripe"
    assert extract_board_token("https://job-boards.greenhouse.io/stripe") == "stripe"
    assert extract_board_token("https://job-boards.greenhouse.io/authenticbrandsgroup/jobs/6148480004") == "authenticbrandsgroup"

    # Legacy board URL
    assert extract_board_token("https://boards.greenhouse.io/airbnb/jobs/67890") == "airbnb"
    assert extract_board_token("https://boards.greenhouse.io/lts") == "lts"

    # Embedded app query param
    assert extract_board_token("https://job-boards.greenhouse.io/embed/job_app?for=spotify&token=123") == "spotify"
    assert extract_board_token("https://boards.greenhouse.io/embed/job_board?for=figma") == "figma"
    assert extract_board_token("https://careers.example.com/embed?for=dropbox&gh_jid=99") == "dropbox"

    # Exclusions / Invalid
    assert extract_board_token("https://job-boards.greenhouse.io/embed/job_app?for=internal&token=123") is None
    assert extract_board_token("https://job-boards.greenhouse.io/jobs/search") is None
    assert extract_board_token("https://my.greenhouse.io/users/sign_in") is None
    assert extract_board_token("https://careers.google.com/jobs/1") is None
    assert extract_board_token("") is None
    assert extract_board_token(None) is None


def test_extract_inertia_version_from_html():
    html_data_page = '<div id="app" data-page="{&quot;component&quot;:&quot;Jobs&quot;,&quot;version&quot;:&quot;abc123hash&quot;}"></div>'
    assert extract_inertia_version_from_html(html_data_page) == "abc123hash"

    html_script = '<script>window.Inertia = {"version": "def456hash"};</script>'
    assert extract_inertia_version_from_html(html_script) == "def456hash"

    assert extract_inertia_version_from_html("<div>No version</div>") is None


def test_fetch_inertia_version_with_mock():
    with patch("urllib.request.urlopen") as mock_open:
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'<div id="app" data-page="{&quot;version&quot;:&quot;testver789&quot;}"></div>'
        mock_open.return_value.__enter__.return_value = mock_resp

        ver = fetch_inertia_version("test_cookie")
        assert ver == "testver789"


def test_parse_inertia_jobs_payload():
    payload = {
        "component": "Jobs/Search",
        "props": {
            "jobs": [
                {
                    "title": "Lead Architect",
                    "company": "Stripe",
                    "url": "https://job-boards.greenhouse.io/stripe/jobs/101",
                },
                {
                    "title": "Staff Architect",
                    "company_name": "Figma",
                    "job_url": "https://boards.greenhouse.io/figma/jobs/202",
                },
                {
                    "title": "Embedded Role",
                    "organization": "Spotify",
                    "apply_url": "https://job-boards.greenhouse.io/embed/job_app?for=spotify&token=303",
                },
            ],
            "page": 1,
            "total_pages": 4,
        },
    }

    extracted, page, total_pages, more_available = parse_inertia_jobs_payload(payload)
    assert page == 1
    assert total_pages == 4
    assert more_available is False
    assert len(extracted) == 3
    assert extracted[0] == {
        "company": "Stripe",
        "board_token": "stripe",
        "url": "https://job-boards.greenhouse.io/stripe/jobs/101",
    }
    assert extracted[1] == {
        "company": "Figma",
        "board_token": "figma",
        "url": "https://boards.greenhouse.io/figma/jobs/202",
    }
    assert extracted[2] == {
        "company": "Spotify",
        "board_token": "spotify",
        "url": "https://job-boards.greenhouse.io/embed/job_app?for=spotify&token=303",
    }


def test_parse_inertia_jobs_payload_alternate_key_and_empty():
    payload_nested = {
        "props": {
            "jobPosts": [
                {
                    "companyName": "Fingerprint",
                    "urlToken": "fingerprint",
                    "publicUrl": "https://fingerprint.com/careers/jobs/apply/?gh_jid=6188157004",
                }
            ],
            "page": 2,
            "totalPages": 5,
            "moreResultsAvailable": True,
        }
    }
    extracted, page, total_pages, more_available = parse_inertia_jobs_payload(payload_nested)
    assert page == 2
    assert total_pages == 5
    assert more_available is True
    assert len(extracted) == 1
    assert extracted[0]["company"] == "Fingerprint"
    assert extracted[0]["board_token"] == "fingerprint"

    assert parse_inertia_jobs_payload({}) == ([], 1, 1, False)


def test_build_search_queries():
    chips = {
        "search_term": ["Architect", "Team Lead"],
        "work_type": ["remote"],
        "employment_type": ["Full time"],
    }
    queries = build_search_queries(chips)
    assert len(queries) == 2
    assert queries[0] == {
        "query": "Architect",
        "work_type[]": ["remote"],
        "employment_type[]": ["Full time"],
    }
    assert queries[1] == {
        "query": "Team Lead",
        "work_type[]": ["remote"],
        "employment_type[]": ["Full time"],
    }


def test_probe_board_reachability_pass():
    with patch("urllib.request.urlopen") as mock_open:
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps({"jobs": [{"id": 1, "title": "Architect"}]}).encode("utf-8")
        mock_open.return_value.__enter__.return_value = mock_resp

        assert probe_board_reachability("stripe") is True


def test_probe_board_reachability_fail_404():
    with patch("urllib.request.urlopen") as mock_open:
        mock_open.side_effect = urllib.error.HTTPError("url", 404, "Not Found", {}, io.BytesIO(b""))
        assert probe_board_reachability("nonexistent_company") is False


def test_deduplicate_against_catalog():
    catalog = make_companies_catalog(
        [
            make_company_row(company_id="lts", name="LTS", ats_token="lts", ats_enabled=True),
            make_company_row(
                company_id="authentic-brands-group",
                name="Authentic Brands Group",
                ats_token="authenticbrandsgroup",
                ats_enabled=True,
            ),
        ]
    )

    discovered = [
        # Already in catalog by ID and token
        {"company": "LTS", "board_token": "lts", "url": "https://job-boards.greenhouse.io/lts"},
        # Already in catalog by token (case-insensitive)
        {"company": "Authentic Brands", "board_token": "authenticbrandsgroup", "url": "https://job-boards.greenhouse.io/authenticbrandsgroup"},
        # Genuinely new
        {"company": "Stripe", "board_token": "stripe", "url": "https://job-boards.greenhouse.io/stripe"},
        # Duplicate within batch
        {"company": "Stripe", "board_token": "stripe", "url": "https://job-boards.greenhouse.io/stripe/jobs/2"},
        # Genuinely new 2
        {"company": "Figma", "board_token": "figma", "url": "https://job-boards.greenhouse.io/figma"},
    ]

    new_candidates = deduplicate_against_catalog(discovered, catalog)
    assert len(new_candidates) == 2
    assert [c["id"] for c in new_candidates] == ["stripe", "figma"]
    assert [c["board_token"] for c in new_candidates] == ["stripe", "figma"]


def test_insert_new_companies_with_probe_results(tmp_path: Path):
    catalog_path = tmp_path / "companies.json"
    catalog = make_companies_catalog(
        [make_company_row(company_id="lts", name="LTS", ats_token="lts", ats_enabled=True)]
    )
    catalog_path.write_text(json.dumps(catalog, indent=2), encoding="utf-8")

    new_candidates = [
        {"id": "stripe", "name": "Stripe", "board_token": "stripe", "url": "https://job-boards.greenhouse.io/stripe"},
        {"id": "closed-corp", "name": "Closed Corp", "board_token": "closedcorp", "url": "https://job-boards.greenhouse.io/closedcorp"},
    ]

    def mock_probe(board_token: str, timeout: int = 30) -> bool:
        return board_token == "stripe"

    with patch("greenhouse.discover_greenhouse_boards.probe_board_reachability", side_effect=mock_probe):
        new_count, enabled_count, disabled_count = insert_new_companies(
            catalog_path,
            new_candidates,
            probe_verification=True,
        )

    assert new_count == 2
    assert enabled_count == 1
    assert disabled_count == 1

    updated = json.loads(catalog_path.read_text(encoding="utf-8"))
    by_id = {c["id"]: c for c in updated["companies"]}

    assert "stripe" in by_id
    assert by_id["stripe"]["ats"]["enabled"] is True
    assert by_id["stripe"]["ats"]["platform"] == "greenhouse"
    assert by_id["stripe"]["ats"]["board_token"] == "stripe"
    assert by_id["stripe"]["ats"]["source"] == "greenhouse_discovery"
    assert by_id["stripe"]["ats"]["detected_at"] is not None

    assert "closed-corp" in by_id
    assert by_id["closed-corp"]["ats"]["enabled"] is False
    assert by_id["closed-corp"]["ats"]["platform"] == "greenhouse"
    assert by_id["closed-corp"]["ats"]["board_token"] == "closedcorp"
    assert by_id["closed-corp"]["ats"]["source"] == "greenhouse_discovery"


def test_load_discovery_criteria(tmp_path: Path):
    criteria_file = tmp_path / "criteria.json"
    criteria_file.write_text(
        json.dumps(
            {
                "criteria": [
                    {
                        "id": "jsc_004",
                        "pipeline": "greenhouse_discovery",
                        "created_on": "2026-09-14T00:00:00Z",
                        "modified_on": "2026-09-14T00:00:00Z",
                        "description": "Test discovery",
                        "search_chips": {"search_term": ["Architect"]},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    loaded = load_discovery_criteria(criteria_file, "jsc_004")
    assert loaded["id"] == "jsc_004"
    assert loaded["pipeline"] == "greenhouse_discovery"

    with pytest.raises(RuntimeError, match="Criteria ID missing: jsc_999"):
        load_discovery_criteria(criteria_file, "jsc_999")


def test_main_graceful_exit_when_no_cookie(tmp_path: Path):
    root = tmp_path / "repo"
    criteria_dir = root / ".ai" / "guardrails"
    companies_dir = root / ".ai" / "history" / "job-search"
    criteria_dir.mkdir(parents=True)
    companies_dir.mkdir(parents=True)

    criteria_file = criteria_dir / "locked-job-search-criteria.json"
    companies_file = companies_dir / "companies.json"
    model_file = criteria_dir / "locked-job-search-data-model.json"

    criteria_file.write_text(
        json.dumps(
            {
                "criteria": [
                    {
                        "id": "jsc_004",
                        "pipeline": "greenhouse_discovery",
                        "created_on": "2026-09-14T00:00:00Z",
                        "modified_on": "2026-09-14T00:00:00Z",
                        "description": "test",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    companies_file.write_text(json.dumps({"companies": []}), encoding="utf-8")
    model_file.write_text(json.dumps({"$schema": "http://json-schema.org/draft-07/schema#"}), encoding="utf-8")

    with patch("greenhouse.discover_greenhouse_boards.get_my_greenhouse_session_cookie", return_value=None):
        exit_code = main(["--repo-root", str(root)])
        assert exit_code == 0


def test_main_auth_failure_graceful_exit(tmp_path: Path):
    root = tmp_path / "repo"
    criteria_dir = root / ".ai" / "guardrails"
    companies_dir = root / ".ai" / "history" / "job-search"
    criteria_dir.mkdir(parents=True)
    companies_dir.mkdir(parents=True)

    criteria_file = criteria_dir / "locked-job-search-criteria.json"
    companies_file = companies_dir / "companies.json"
    model_file = criteria_dir / "locked-job-search-data-model.json"

    criteria_file.write_text(
        json.dumps(
            {
                "criteria": [
                    {
                        "id": "jsc_004",
                        "pipeline": "greenhouse_discovery",
                        "created_on": "2026-09-14T00:00:00Z",
                        "modified_on": "2026-09-14T00:00:00Z",
                        "description": "test",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    companies_file.write_text(json.dumps({"companies": []}), encoding="utf-8")
    model_file.write_text(json.dumps({"$schema": "http://json-schema.org/draft-07/schema#"}), encoding="utf-8")

    with patch("greenhouse.discover_greenhouse_boards.run_discovery", return_value=([], False)):
        exit_code = main(["--repo-root", str(root), "--session-cookie", "_my_greenhouse_session=expired"])
        assert exit_code == 0


def test_main_session_cookie_from_auth_file(tmp_path: Path):
    root = tmp_path / "repo"
    criteria_dir = root / ".ai" / "guardrails"
    companies_dir = root / ".ai" / "history" / "job-search"
    auth_dir = root / ".auth"
    criteria_dir.mkdir(parents=True)
    companies_dir.mkdir(parents=True)
    auth_dir.mkdir(parents=True)

    criteria_file = criteria_dir / "locked-job-search-criteria.json"
    companies_file = companies_dir / "companies.json"
    model_file = criteria_dir / "locked-job-search-data-model.json"
    auth_file = auth_dir / "greenhouse_session.txt"

    criteria_file.write_text(
        json.dumps(
            {
                "criteria": [
                    {
                        "id": "jsc_004",
                        "pipeline": "greenhouse_discovery",
                        "created_on": "2026-09-14T00:00:00Z",
                        "modified_on": "2026-09-14T00:00:00Z",
                        "description": "test",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    companies_file.write_text(json.dumps({"companies": []}), encoding="utf-8")
    model_file.write_text(json.dumps({"$schema": "http://json-schema.org/draft-07/schema#"}), encoding="utf-8")
    auth_file.write_text("raw_auth_token_123", encoding="utf-8")

    with patch("greenhouse.discover_greenhouse_boards.run_discovery") as mock_disc:
        mock_disc.return_value = ([], True)
        exit_code = main(["--repo-root", str(root)])
        assert exit_code == 0
        mock_disc.assert_called_once()
        args, kwargs = mock_disc.call_args
        assert kwargs["session_cookie"] == "_session_id=raw_auth_token_123"


def test_extract_greenhouse_cookies_mock_sqlite(tmp_path: Path):
    db_path = tmp_path / "Cookies"
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute(
        "CREATE TABLE cookies (host_key TEXT, name TEXT, value TEXT, encrypted_value BLOB)"
    )
    cursor.execute(
        "INSERT INTO cookies VALUES ('.greenhouse.io', '_session_id', 'mock_session_123', X'')"
    )
    cursor.execute(
        "INSERT INTO cookies VALUES ('.other.com', 'other_cookie', 'other_val', X'')"
    )
    conn.commit()
    conn.close()

    with patch("greenhouse.chrome_cookie.get_chrome_cookie_db_path", return_value=db_path):
        cookies = extract_greenhouse_cookies()
        assert cookies == {"_session_id": "mock_session_123"}

        session_str = get_my_greenhouse_session_cookie()
        assert session_str == "_session_id=mock_session_123"
