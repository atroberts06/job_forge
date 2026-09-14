"""Extraction precedence and arrangement-gate criteria tests."""

from __future__ import annotations

from greenhouse.normalize import extract_work_location_type, normalize_greenhouse_job, now_iso, parse_posted_at
from greenhouse.fetch_greenhouse_jobs import matches_criteria
from conftest import make_job, make_raw_greenhouse


def test_parse_posted_at_relative_days():
    assert parse_posted_at("4 days ago", "2026-01-03") == "2025-12-30"


def test_parse_posted_at_iso_datetime():
    assert parse_posted_at("2026-01-03T14:32:40Z", "2026-01-10") == "2026-01-03"


def test_parse_posted_at_missing():
    assert parse_posted_at(None, "2026-01-03") is None
    assert parse_posted_at("", "2026-01-03") is None


def test_parse_posted_at_slash_mdy():
    assert parse_posted_at("09/04/2026", "2026-09-06") == "2026-09-04"
    assert parse_posted_at("9/4/2026", "2026-09-06") == "2026-09-04"


def test_parse_posted_at_unpadded_iso_date():
    assert parse_posted_at("2026-9-4", "2026-09-06") == "2026-09-04"


def test_greenhouse_ignores_updated_at_for_posted_at():
    raw = make_raw_greenhouse()
    raw["updated_at"] = "2026-01-01T00:00:00Z"
    raw.pop("first_published", None)
    raw.pop("created_at", None)
    job = normalize_greenhouse_job(
        raw,
        board_token="lts",
        company="LTS",
        pull_date="2026-01-03",
        status_updated_at="2026-01-03T15:00:00Z",
    )
    assert job["posted_at"] is None


def test_greenhouse_uses_created_at_for_posted_at():
    raw = make_raw_greenhouse()
    raw["created_at"] = "2025-12-30T12:00:00Z"
    raw.pop("first_published", None)
    job = normalize_greenhouse_job(
        raw,
        board_token="lts",
        company="LTS",
        pull_date="2026-01-03",
        status_updated_at="2026-01-03T15:00:00Z",
    )
    assert job["posted_at"] == "2025-12-30"


def test_metadata_allowlist_takes_precedence_over_location():
    wlt = extract_work_location_type(
        "New York, NY",
        [{"name": "NYC Office"}],
        [{"name": "Workplace Type", "value": "Hybrid"}],
    )
    assert wlt == "hybrid"


def test_unrecognized_metadata_falls_through_to_location():
    wlt = extract_work_location_type(
        "United States - Remote",
        [],
        [{"name": "Workplace Type", "value": "Flexible"}],
    )
    assert wlt == "remote"


def test_non_allowlisted_metadata_ignored():
    wlt = extract_work_location_type(
        "New York, NY",
        [],
        [{"name": "Department", "value": "Remote Team"}],
    )
    assert wlt == "unknown"


def test_location_remote_token():
    assert extract_work_location_type("Herndon, VA - Remote", [], None) == "remote"


def test_office_hybrid_token():
    assert extract_work_location_type(None, [{"name": "Hybrid - NYC"}], None) == "hybrid"


def test_explicit_onsite_token():
    assert extract_work_location_type("New York, NY - On-Site", [], None) == "onsite"


def test_bare_geography_yields_unknown():
    assert extract_work_location_type("New York, NY", [], None) == "unknown"


def test_empty_location_yields_unknown():
    assert extract_work_location_type("", [], None) == "unknown"
    assert extract_work_location_type(None, None, None) == "unknown"


def test_description_text_never_scanned_for_remote():
    raw = make_raw_greenhouse(
        job_id=4296004009,
        title="Technical Architect",
        location_name="United States",
        content="<p>Demonstrated experience in a remote work environment.</p>",
    )
    job = normalize_greenhouse_job(
        raw,
        board_token="lts",
        company="LTS",
        pull_date="2026-08-11",
        status_updated_at="2026-08-11T15:00:00Z",
        prior_ids=set(),
    )
    assert "remote work environment" in job["description_text"].lower()
    assert job["work_location_type"] == "unknown"


def test_now_iso_utc_z_suffix():
    ts = now_iso()
    assert ts.endswith("Z")
    assert "+00:00" not in ts
    assert "T" in ts


def test_arrangement_remote_bypasses_geography(criteria):
    job = make_job(
        work_location_type="remote",
        location="Herndon, VA, United States - Remote",
    )
    assert matches_criteria(job, criteria) is True


def test_arrangement_remote_excluded(criteria):
    cfg = {**criteria, "work_location_type": {**criteria["work_location_type"], "include_remote": False}}
    job = make_job(work_location_type="remote", location="Remote")
    assert matches_criteria(job, cfg) is False


def test_arrangement_unknown_passes_gate_geography_filters(criteria):
    ok = make_job(work_location_type="unknown", location="New York, NY")
    bad = make_job(work_location_type="unknown", location="Austin, TX")
    assert matches_criteria(ok, criteria) is True
    assert matches_criteria(bad, criteria) is False


def test_arrangement_onsite_toggle_false(criteria):
    job = make_job(work_location_type="onsite", location="New York, NY")
    assert matches_criteria(job, criteria) is False


def test_arrangement_hybrid_requires_geography(criteria):
    ok = make_job(work_location_type="hybrid", location="New York, NY")
    bad = make_job(work_location_type="hybrid", location="Chicago, IL")
    assert matches_criteria(ok, criteria) is True
    assert matches_criteria(bad, criteria) is False
