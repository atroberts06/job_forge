"""TalentBrew list/detail parse and normalize tests. Offline fixtures only."""

from __future__ import annotations

import json
from pathlib import Path

from greenhouse.fetch_greenhouse_jobs import matches_criteria
from talentbrew.normalize import (
    accepted_list_card,
    criteria_for_matching,
    extract_arrangement,
    normalize_talentbrew_job,
    parse_detail_page,
    parse_facet_catalog,
    parse_list_cards,
    parse_workday_requisition_id,
    resolve_facet_filters,
    titles_include_all,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"

JSC_003_TITLES = {
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


def _card_by_seq(cards: list[dict], seq: str) -> dict:
    for card in cards:
        accepted = accepted_list_card(card)
        if accepted and accepted["source_job_id"] == seq:
            return accepted
    raise AssertionError(f"missing card {seq}")


def test_list_parse_uses_anchor_not_inner_span_or_save_button():
    html = (FIXTURES / "list_results_sample.html").read_text(encoding="utf-8")
    cards = parse_list_cards(html)
    assert len(cards) == 1
    accepted = accepted_list_card(cards[0])
    assert accepted is not None
    assert accepted["source_job_id"] == "96262041488"
    assert accepted["org_id"] == "1732"
    assert accepted["title"] == "Senior Lead Information Security Consultant (AI)"
    assert accepted["location"] == "McLean, VA"
    assert accepted["posted"] == "09/04/2026"
    assert "button" not in accepted["href"]


def test_list_card_skipped_when_href_and_data_job_id_disagree():
    html = """
    <ul><li>
      <a href="/job/mclean/role/1732/111" data-job-id="222">
        <h2>Role</h2><span class="job-location">McLean, VA</span>
      </a>
    </li></ul>
    """
    cards = parse_list_cards(html)
    assert accepted_list_card(cards[0]) is None


def test_detail_parse_requisition_and_ats_description():
    html = (FIXTURES / "detail_sample.html").read_text(encoding="utf-8")
    detail = parse_detail_page(html)
    assert parse_workday_requisition_id(detail) == "R244159"
    assert detail["span_job_id"] == "R244159"
    assert detail["meta_job_ats_req_id"] == "R244159"
    assert detail["json_ld_identifier"] == "R244159"
    assert detail["category"] == "Cyber"
    assert detail["experience"] == "Sr. Manager"
    assert "McLean, Virginia" in detail["primary_address"]
    assert "Key Responsibilities" in detail["description_text"] or "Responsibilities:" in detail["description_text"]
    assert "Act as an Information Security point of contact" in detail["description_text"]
    assert detail["html_remote_facet"] == "Not-Remote"
    assert detail["date_posted_ld"] == "2026-9-4"


def test_normalize_sample_includes_workday_requisition_id():
    list_html = (FIXTURES / "list_results_sample.html").read_text(encoding="utf-8")
    detail = parse_detail_page((FIXTURES / "detail_sample.html").read_text(encoding="utf-8"))
    card = accepted_list_card(parse_list_cards(list_html)[0])
    assert card is not None
    job = normalize_talentbrew_job(
        card,
        detail,
        board_token="capital-one",
        company="Capital One",
        origin="https://www.capitalonecareers.com",
        pull_date="2026-09-06",
        status_updated_at="2026-09-06T13:23:51Z",
    )
    assert job["id"] == "talentbrew:capital-one:96262041488"
    assert job["source_job_id"] == "96262041488"
    assert job["workday_requisition_id"] == "R244159"
    assert job["location"] == "McLean, VA"
    assert job["work_location_type"] == "onsite"
    assert job["posted_at"] == "2026-09-04"
    assert job["raw"]["org_id"] == "1732"
    assert job["raw"]["html_remote_facet"] == "Not-Remote"
    assert job["url"].endswith("/1732/96262041488")
    golden = {
        "id": job["id"],
        "source_job_id": job["source_job_id"],
        "workday_requisition_id": job["workday_requisition_id"],
        "status": job["status"],
        "title": job["title"],
        "company": job["company"],
        "location": job["location"],
        "work_location_type": job["work_location_type"],
        "url": job["url"],
        "pulled_at": job["pulled_at"],
        "posted_at": job["posted_at"],
        "raw": job["raw"],
    }
    expected_path = FIXTURES / "golden_sample_job.json"
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    assert golden == expected


def test_mclean_onsite_drops_under_jsc_003_geo():
    list_html = (FIXTURES / "list_results_sample.html").read_text(encoding="utf-8")
    detail = parse_detail_page((FIXTURES / "detail_sample.html").read_text(encoding="utf-8"))
    card = accepted_list_card(parse_list_cards(list_html)[0])
    assert card is not None
    job = normalize_talentbrew_job(
        card,
        detail,
        board_token="capital-one",
        company="Capital One",
        origin="https://www.capitalonecareers.com",
        pull_date="2026-09-06",
        status_updated_at="2026-09-06T13:23:51Z",
    )
    job["title"] = "Lead Software Engineer"
    assert matches_criteria(job, criteria_for_matching(JSC_003_TITLES)) is False


def test_ny_engineer_kept_under_jsc_003():
    cards = parse_list_cards((FIXTURES / "list_results_mixed.html").read_text(encoding="utf-8"))
    card = _card_by_seq(cards, "11111111111")
    detail = parse_detail_page((FIXTURES / "detail_keep.html").read_text(encoding="utf-8"))
    job = normalize_talentbrew_job(
        card,
        detail,
        board_token="capital-one",
        company="Capital One",
        origin="https://www.capitalonecareers.com",
        pull_date="2026-09-06",
        status_updated_at="2026-09-06T13:23:51Z",
    )
    assert job["location"] == "New York, NY"
    assert matches_criteria(job, criteria_for_matching(JSC_003_TITLES)) is True


def test_titles_include_all_sentinel_skips_include_and_strips_token():
    criteria = {
        "titles": {"include": ["all", "architect"], "exclude": ["intern"]},
        "locations": {"include": []},
        "work_location_type": {
            "include_remote": True,
            "include_hybrid": True,
            "include_onsite": True,
        },
    }
    assert titles_include_all(criteria) is True
    matched = criteria_for_matching(criteria)
    assert matched["titles"]["include"] == []
    job = {
        "title": "Small Business Teller",
        "location": "McLean, VA",
        "work_location_type": "onsite",
        "description_text": "",
    }
    assert matches_criteria(job, matched) is True
    intern = dict(job, title="Intern Teller")
    assert matches_criteria(intern, matched) is False


def test_facet_resolve_fail_closed_unknown_label():
    catalog = parse_facet_catalog((FIXTURES / "filters_sample.html").read_text(encoding="utf-8"))
    resolved = resolve_facet_filters({"teams": ["Technology"], "remote": None}, catalog)
    assert resolved[0]["id"] == "9001"
    try:
        resolve_facet_filters({"teams": ["Not A Real Team"]}, catalog)
    except RuntimeError as exc:
        assert "Unknown TalentBrew facet label" in str(exc)
    else:
        raise AssertionError("expected fail closed")


def test_arrangement_remote_from_primary_address_pipe():
    assert (
        extract_arrangement(
            title="Engineer",
            primary_address="Richmond, Virginia | Remote",
            header_location="",
            html_remote_facet=None,
            json_ld=None,
        )
        == "remote"
    )


def test_arrangement_does_not_scan_description():
    assert (
        extract_arrangement(
            title="Engineer",
            primary_address="McLean, Virginia",
            header_location="McLean, Virginia",
            html_remote_facet="Not-Remote",
            json_ld={"description": "This role is fully remote and hybrid optional."},
        )
        == "onsite"
    )
