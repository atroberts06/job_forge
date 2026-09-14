"""SerpApi puller quota and pagination tests."""

from __future__ import annotations

import importlib.util
import json
import urllib.parse
from datetime import date
from pathlib import Path


def _load_fetch():
    path = Path(__file__).resolve().parents[1] / "fetch_serpapi_jobs.py"
    spec = importlib.util.spec_from_file_location("fetch_serpapi_jobs", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Response:
    def __init__(self, payload: dict):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def _account(left: int, *, used: int = 0, searches_per_month: int = 250) -> dict:
    return {
        "this_month_usage": used,
        "plan_searches_left": left,
        "searches_per_month": searches_per_month,
    }


def _sample_payload(*, next_token: str | None = None) -> dict:
    fixture = Path(__file__).resolve().parent / "fixtures" / "jobs_results_sample.json"
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    payload["search_metadata"] = {"status": "Success", "id": "live_result"}
    if next_token:
        payload["serpapi_pagination"] = {"next_page_token": next_token}
    return payload


def _write_repo(
    tmp_path: Path,
    *,
    terms: int = 3,
    pull_date: str = "2026-01-31",
    max_searches: int = 6,
    locations: list[str] | None = None,
    include_remote: bool = False,
) -> Path:
    root = tmp_path / "repo"
    job_search = root / ".ai" / "history" / "job-search"
    (job_search / "serpapi" / "src").mkdir(parents=True)
    (job_search / "companies.json").write_text('{"companies": []}\n', encoding="utf-8")

    guardrails = root / ".ai" / "guardrails"
    guardrails.mkdir(parents=True)
    criteria = {
        "criteria": [
            {
                "id": "jsc_001",
                "pipeline": "greenhouse",
                "titles": {"include": [], "exclude": [], "match_mode": "any"},
            },
            {
                "id": "jsc_002",
                "pipeline": "google_jobs",
                "search_query": {"include": [f"query {idx}" for idx in range(terms)]},
                "location": {"include": ["New Jersey"] if locations is None else locations},
                "include_remote": include_remote,
                "max_searches": max_searches,
                "country_code": "us",
                "language_code": "en",
                "google_domain": "",
                "search_radius_kilometers": None,
                "google_filter_token": "",
                "industry_query": "education",
                "next_page_token": "",
                "date_posted": "yesterday",
            },
        ]
    }
    (guardrails / "locked-job-search-criteria.json").write_text(
        json.dumps(criteria, indent=2) + "\n",
        encoding="utf-8",
    )
    (guardrails / "locked-job-search-data-model.json").write_text("{}\n", encoding="utf-8")
    return root


def _mock_urlopen(monkeypatch, mod, *, account: dict, search_payloads: list[dict] | None = None):
    calls: list[str] = []
    remaining_searches = list(search_payloads or [])

    def fake_urlopen(req, timeout=60):
        url = req.full_url
        calls.append(url)
        if "account.json" in url:
            return _Response(account)
        if "search.json" in url:
            payload = remaining_searches.pop(0) if remaining_searches else _sample_payload()
            return _Response(payload)
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
    return calls


def _search_urls(calls: list[str]) -> list[str]:
    return [url for url in calls if "search.json" in url]


def _prepare(monkeypatch, mod, *, today: date = date(2026, 1, 31)) -> None:
    monkeypatch.setenv("SERPAPI_API_KEY", "test-key")
    monkeypatch.setattr(mod, "utc_today", lambda: today)
    monkeypatch.setattr(mod, "validate_instance", lambda *args, **kwargs: [])
    monkeypatch.setattr(mod, "validate_pull_files", lambda *args, **kwargs: [])


def test_plan_searches_left_zero_skips_without_search_http(tmp_path, monkeypatch):
    mod = _load_fetch()
    _prepare(monkeypatch, mod)
    root = _write_repo(tmp_path)
    calls = _mock_urlopen(monkeypatch, mod, account=_account(0))

    assert mod.main(["--repo-root", str(root), "--date", "2026-01-31"]) == 0
    assert _search_urls(calls) == []


def test_planned_exceeds_left_skips_without_search_http(tmp_path, monkeypatch):
    mod = _load_fetch()
    _prepare(monkeypatch, mod)
    root = _write_repo(tmp_path)
    calls = _mock_urlopen(monkeypatch, mod, account=_account(5))

    assert mod.main(["--repo-root", str(root), "--date", "2026-01-31"]) == 0
    assert _search_urls(calls) == []


def test_left_six_with_next_tokens_fetches_three_page_pairs(tmp_path, monkeypatch):
    mod = _load_fetch()
    _prepare(monkeypatch, mod)
    root = _write_repo(tmp_path)
    payloads = []
    for idx in range(3):
        payloads.extend([_sample_payload(next_token=f"token-{idx}"), _sample_payload()])
    calls = _mock_urlopen(monkeypatch, mod, account=_account(6), search_payloads=payloads)

    assert mod.main(["--repo-root", str(root), "--date", "2026-01-31"]) == 0
    assert len(_search_urls(calls)) == 6


def test_no_next_page_token_fetches_page_one_only(tmp_path, monkeypatch):
    mod = _load_fetch()
    _prepare(monkeypatch, mod)
    root = _write_repo(tmp_path)
    calls = _mock_urlopen(monkeypatch, mod, account=_account(6), search_payloads=[_sample_payload()] * 3)

    assert mod.main(["--repo-root", str(root), "--date", "2026-01-31"]) == 0
    assert len(_search_urls(calls)) == 3


def test_daily_cap_limits_run_to_six_searches(tmp_path, monkeypatch):
    mod = _load_fetch()
    _prepare(monkeypatch, mod, today=date(2026, 1, 17))
    root = _write_repo(tmp_path, max_searches=8)
    payloads = []
    for idx in range(3):
        payloads.extend([_sample_payload(next_token=f"token-{idx}"), _sample_payload()])
    calls = _mock_urlopen(monkeypatch, mod, account=_account(90), search_payloads=payloads)

    assert mod.main(["--repo-root", str(root), "--date", "2026-01-17"]) == 0
    assert len(_search_urls(calls)) == 6


def test_existing_today_jobs_skips_without_http(tmp_path, monkeypatch):
    mod = _load_fetch()
    _prepare(monkeypatch, mod)
    root = _write_repo(tmp_path)
    out_path = root / ".ai" / "history" / "job-search" / "serpapi" / "src" / "2026-01-31" / "jobs.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text('{"platform":"serpapi","pulled_at":"2026-01-31T00:00:00Z","jobs":[]}\n', encoding="utf-8")

    def fail_urlopen(req, timeout=60):
        raise AssertionError("urlopen should not be called")

    monkeypatch.setattr(mod.urllib.request, "urlopen", fail_urlopen)
    assert mod.main(["--repo-root", str(root), "--date", "2026-01-31"]) == 0


def test_page_two_request_keeps_date_filter_q_and_uds(tmp_path, monkeypatch):
    mod = _load_fetch()
    _prepare(monkeypatch, mod)
    root = _write_repo(tmp_path, terms=1)
    calls = _mock_urlopen(
        monkeypatch,
        mod,
        account=_account(6),
        search_payloads=[_sample_payload(next_token="next-1"), _sample_payload()],
    )

    assert mod.main(["--repo-root", str(root), "--date", "2026-01-31"]) == 0
    page_two = [url for url in _search_urls(calls) if "next_page_token=" in url]
    assert len(page_two) == 1
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(page_two[0]).query)
    assert qs["uds"] == [mod.DATE_POSTED_CATALOG["yesterday"]["uds"]]
    assert "since yesterday" in qs["q"][0]


def _lts_row() -> dict:
    return {
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


def _catalog(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_successful_fetch_upserts_catalog_without_industry_or_lts_clobber(tmp_path, monkeypatch):
    mod = _load_fetch()
    _prepare(monkeypatch, mod)
    root = _write_repo(tmp_path, terms=1)
    catalog_path = root / ".ai" / "history" / "job-search" / "companies.json"
    catalog_path.write_text(json.dumps({"companies": [_lts_row()]}, indent=2) + "\n", encoding="utf-8")
    _mock_urlopen(monkeypatch, mod, account=_account(6), search_payloads=[_sample_payload()])

    assert mod.main(["--repo-root", str(root), "--date", "2026-01-31"]) == 0

    rows = {row["id"]: row for row in _catalog(catalog_path)["companies"]}
    assert rows["lts"]["ats"]["enabled"] is True
    assert rows["lts"]["ats"]["platform"] == "greenhouse"
    assert rows["lts"]["ats"]["source"] == "manual"
    assert rows["lts"]["industries"] == []

    empty_ats = {
        "enabled": False,
        "platform": "",
        "board_token": "",
        "career_url": "",
        "source": "",
        "detected_at": None,
    }
    starbucks = rows["starbucks"]
    assert starbucks["name"] == "Starbucks"
    assert starbucks["industries"] == []
    assert starbucks["ats"] == empty_ats
    assert starbucks["company"]["platform"] == "starbucks"
    assert starbucks["company"]["board_token"] == "starbucks"
    assert starbucks["company"]["source"] == ""
    assert starbucks["company"]["enabled"] is False
    assert starbucks["company"]["career_url"] == ""
    assert starbucks["company"]["detected_at"] is None

    aramark = rows["aramark"]
    assert aramark["name"] == "Aramark"
    assert aramark["industries"] == []
    assert aramark["ats"] == empty_ats
    assert aramark["company"]["platform"] == "aramark"
    assert aramark["company"]["board_token"] == "aramark"
    assert aramark["company"]["source"] == "serpapi"
    assert aramark["company"]["enabled"] is False
    assert "aramark" in aramark["company"]["career_url"].lower()
    assert aramark["company"]["career_url"] == "https://aramarkcareers.com"
    assert aramark["company"]["detected_at"] == "2026-01-31"


def test_upsert_companies_does_not_tag_or_clobber_industries(tmp_path):
    mod = _load_fetch()
    catalog_path = tmp_path / "companies.json"
    tagged = _lts_row()
    tagged["id"] = "acme"
    tagged["name"] = "Acme"
    tagged["industries"] = ["finance"]
    tagged["ats"]["enabled"] = False
    tagged["ats"]["source"] = "serpapi"
    tagged["company"]["platform"] = "acme"
    tagged["company"]["board_token"] = "acme"
    tagged["company"]["source"] = "serpapi"
    tagged["company"]["career_url"] = ""
    catalog_path.write_text(
        json.dumps({"companies": [_lts_row(), tagged]}, indent=2) + "\n",
        encoding="utf-8",
    )

    mod.upsert_companies(
        catalog_path,
        [
            {
                "company": "Acme",
                "url": "https://job-boards.greenhouse.io/acme/jobs/1",
            },
            {
                "company": "LTS",
                "url": "https://job-boards.greenhouse.io/other/jobs/2",
            },
            {
                "company": "New Co",
                "url": "https://www.indeed.com/viewjob?jk=abc",
            },
        ],
        "2026-01-31",
    )

    rows = {row["id"]: row for row in _catalog(catalog_path)["companies"]}
    assert rows["acme"]["industries"] == ["finance"]
    assert rows["acme"]["ats"]["platform"] == "greenhouse"
    assert rows["acme"]["ats"]["board_token"] == "lts"
    assert rows["acme"]["ats"]["career_url"] == "https://job-boards.greenhouse.io/lts"
    assert rows["acme"]["ats"]["enabled"] is False
    assert rows["acme"]["ats"]["detected_at"] is None
    assert rows["acme"]["company"]["detected_at"] is None
    assert rows["acme"]["company"]["platform"] == "acme"
    assert rows["acme"]["company"]["board_token"] == "acme"
    assert rows["lts"]["ats"]["enabled"] is True
    assert rows["lts"]["ats"]["board_token"] == "lts"
    assert rows["lts"]["company"]["career_url"] == "https://lts.com"
    assert rows["new-co"]["industries"] == []
    assert rows["new-co"]["ats"] == {
        "enabled": False,
        "platform": "",
        "board_token": "",
        "career_url": "",
        "source": "",
        "detected_at": None,
    }
    assert rows["new-co"]["company"]["career_url"] == ""
    assert rows["new-co"]["company"]["source"] == ""
    assert rows["new-co"]["company"]["platform"] == "new-co"
    assert rows["new-co"]["company"]["board_token"] == "new-co"
    assert rows["new-co"]["company"]["detected_at"] is None
    assert rows["acme"]["company"]["career_url"] == ""


def test_upsert_leaves_ats_untouched_without_ats_url_then_fills_on_ats_url(tmp_path):
    mod = _load_fetch()
    catalog_path = tmp_path / "companies.json"
    catalog_path.write_text(json.dumps({"companies": []}, indent=2) + "\n", encoding="utf-8")

    mod.upsert_companies(
        catalog_path,
        [{"company": "Acme", "url": "https://www.indeed.com/viewjob?jk=1"}],
        "2026-01-31",
    )
    row_after_indeed = _catalog(catalog_path)["companies"][0]
    ats_after_indeed = row_after_indeed["ats"]
    assert ats_after_indeed["platform"] == ""
    assert ats_after_indeed["source"] == ""
    assert ats_after_indeed["board_token"] == ""
    assert ats_after_indeed["career_url"] == ""
    assert ats_after_indeed["detected_at"] is None
    assert row_after_indeed["company"]["detected_at"] is None

    mod.upsert_companies(
        catalog_path,
        [{"company": "Acme", "url": "https://job-boards.greenhouse.io/acme/jobs/1"}],
        "2026-02-01",
    )
    row_after_greenhouse = _catalog(catalog_path)["companies"][0]
    ats_after_greenhouse = row_after_greenhouse["ats"]
    assert ats_after_greenhouse["platform"] == "greenhouse"
    assert ats_after_greenhouse["source"] == "serpapi"
    assert ats_after_greenhouse["board_token"] == "acme"
    assert ats_after_greenhouse["detected_at"] == "2026-02-01"
    assert row_after_greenhouse["company"]["detected_at"] is None

    mod.upsert_companies(
        catalog_path,
        [{"company": "Acme", "url": "https://www.linkedin.com/jobs/view/1"}],
        "2026-02-02",
    )
    ats_after_linkedin = _catalog(catalog_path)["companies"][0]["ats"]
    assert ats_after_linkedin == ats_after_greenhouse
    assert _catalog(catalog_path)["companies"][0]["company"]["detected_at"] is None
    assert _catalog(catalog_path)["companies"][0]["company"]["career_url"] == ""


def test_upsert_stores_career_url_only_when_host_matches_slot(tmp_path):
    mod = _load_fetch()
    catalog_path = tmp_path / "companies.json"
    catalog_path.write_text(
        json.dumps(
            {
                "companies": [
                    {
                        "id": "accenture",
                        "name": "Accenture",
                        "company_url": "",
                        "industries": [],
                        "ats": {
                            "enabled": False,
                            "platform": "",
                            "board_token": "",
                            "career_url": "",
                            "source": "",
                            "detected_at": None,
                        },
                        "company": {
                            "enabled": False,
                            "platform": "accenture",
                            "board_token": "accenture",
                            "career_url": "https://jooble.org/jdp/1?utm_campaign=google_jobs_apply",
                            "source": "serpapi",
                            "detected_at": "2026-01-30",
                        },
                    }
                ]
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    mod.upsert_companies(
        catalog_path,
        [
            {
                "company": "Accenture",
                "url": "https://jooble.org/jdp/1?utm_campaign=google_jobs_apply",
            },
            {
                "company": "First Citizens Bank",
                "url": "https://jobs.firstcitizens.com/jobs/35183?utm_campaign=google_jobs_apply",
            },
            {
                "company": "Acme",
                "url": "https://job-boards.greenhouse.io/acme/jobs/1",
            },
            {
                "company": "No Path Co",
                "url": "https://job-boards.greenhouse.io/",
            },
        ],
        "2026-01-31",
    )

    rows = {row["id"]: row for row in _catalog(catalog_path)["companies"]}
    assert rows["accenture"]["company"]["career_url"] == (
        "https://jooble.org/jdp/1?utm_campaign=google_jobs_apply"
    )
    assert rows["accenture"]["ats"]["career_url"] == ""
    assert rows["accenture"]["company"]["detected_at"] == "2026-01-30"
    assert rows["first-citizens-bank"]["company"]["career_url"] == "https://jobs.firstcitizens.com"
    assert rows["first-citizens-bank"]["ats"] == {
        "enabled": False,
        "platform": "",
        "board_token": "",
        "career_url": "",
        "source": "",
        "detected_at": None,
    }
    assert rows["acme"]["ats"]["platform"] == "greenhouse"
    assert rows["acme"]["ats"]["board_token"] == "acme"
    assert rows["acme"]["ats"]["career_url"] == "https://job-boards.greenhouse.io/acme/jobs/1"
    assert rows["acme"]["company"]["career_url"] == ""
    assert rows["no-path-co"]["ats"]["career_url"] == ""
    assert rows["no-path-co"]["ats"]["platform"] == ""
    assert rows["no-path-co"]["company"]["career_url"] == ""


def test_upsert_first_fills_blank_fields_and_does_not_replace_populated(tmp_path):
    mod = _load_fetch()
    catalog_path = tmp_path / "companies.json"
    catalog_path.write_text(json.dumps({"companies": []}, indent=2) + "\n", encoding="utf-8")

    mod.upsert_companies(
        catalog_path,
        [{"company": "Acme", "url": "https://www.acme.com/jobs/1"}],
        "2026-01-31",
    )
    first = _catalog(catalog_path)["companies"][0]
    assert first["company"]["career_url"] == "https://www.acme.com"
    assert first["company"]["source"] == "serpapi"
    assert first["company"]["detected_at"] == "2026-01-31"
    assert first["ats"]["career_url"] == ""

    mod.upsert_companies(
        catalog_path,
        [
            {"company": "Acme", "url": "https://jobs.acme.com/roles/2"},
            {"company": "Acme", "url": "https://job-boards.greenhouse.io/acme/jobs/1"},
        ],
        "2026-02-01",
    )
    second = _catalog(catalog_path)["companies"][0]
    assert second["company"]["career_url"] == "https://www.acme.com"
    assert second["company"]["detected_at"] == "2026-01-31"
    assert second["ats"]["platform"] == "greenhouse"
    assert second["ats"]["board_token"] == "acme"
    assert second["ats"]["career_url"] == "https://job-boards.greenhouse.io/acme/jobs/1"
    assert second["ats"]["detected_at"] == "2026-02-01"

    mod.upsert_companies(
        catalog_path,
        [{"company": "Acme", "url": "https://job-boards.greenhouse.io/acme/jobs/999"}],
        "2026-02-02",
    )
    third = _catalog(catalog_path)["companies"][0]
    assert third["ats"]["career_url"] == "https://job-boards.greenhouse.io/acme/jobs/1"
    assert third["ats"]["detected_at"] == "2026-02-01"
    assert third["company"]["career_url"] == "https://www.acme.com"


def test_source_stamped_serpapi_on_first_fill_then_locked(tmp_path):
    mod = _load_fetch()
    catalog_path = tmp_path / "companies.json"
    catalog_path.write_text(json.dumps({"companies": []}, indent=2) + "\n", encoding="utf-8")

    mod.upsert_companies(
        catalog_path,
        [{"company": "Acme", "url": "https://www.indeed.com/viewjob?jk=1"}],
        "2026-01-31",
    )
    skeleton = _catalog(catalog_path)["companies"][0]
    assert skeleton["ats"]["source"] == ""
    assert skeleton["company"]["source"] == ""

    mod.upsert_companies(
        catalog_path,
        [{"company": "Acme", "url": "https://www.acme.com/jobs/1"}],
        "2026-02-01",
    )
    filled = _catalog(catalog_path)["companies"][0]
    assert filled["company"]["source"] == "serpapi"
    assert filled["company"]["career_url"] == "https://www.acme.com"
    assert filled["ats"]["source"] == ""

    mod.upsert_companies(
        catalog_path,
        [{"company": "Acme", "url": "https://jobs.acme.com/jobs/2"}],
        "2026-02-02",
    )
    locked = _catalog(catalog_path)["companies"][0]
    assert locked["company"]["source"] == "serpapi"
    assert locked["company"]["career_url"] == "https://www.acme.com"


def test_manual_source_is_reserved_for_user_input(tmp_path):
    mod = _load_fetch()
    catalog_path = tmp_path / "companies.json"
    row = _lts_row()
    catalog_path.write_text(json.dumps({"companies": [row]}, indent=2) + "\n", encoding="utf-8")

    mod.upsert_companies(
        catalog_path,
        [
            {"company": "LTS", "url": "https://lts.com/jobs/1"},
            {"company": "LTS", "url": "https://job-boards.greenhouse.io/other/jobs/2"},
        ],
        "2026-01-31",
    )
    after = _catalog(catalog_path)["companies"][0]
    assert after["ats"]["source"] == "manual"
    assert after["company"]["source"] == "manual"
    assert after["ats"]["career_url"] == "https://job-boards.greenhouse.io/lts"
    assert after["company"]["career_url"] == "https://lts.com"
    assert after["ats"]["board_token"] == "lts"


def test_empty_location_is_nationwide_regardless_of_include_remote():
    mod = _load_fetch()
    remote_off = {
        "search_query": {"include": ["team lead", "integration architect"]},
        "location": {"include": []},
        "include_remote": False,
    }
    remote_on = {**remote_off, "include_remote": True}
    expected = [("team lead", None), ("integration architect", None)]
    assert mod.build_fan_out(remote_off) == expected
    assert mod.build_fan_out(remote_on) == expected
    params = mod.build_search_params(
        remote_off,
        "team lead",
        None,
        {"q_suffix": "since yesterday", "uds": "token"},
    )
    assert "location" not in {k: v for k, v in params.items() if v not in (None, "")} or params.get("location") in (None, "")
    assert "ltype" not in params
    remote_params = mod.build_search_params(
        remote_on,
        "team lead",
        None,
        {"q_suffix": "since yesterday", "uds": "token"},
    )
    assert remote_params.get("ltype") == 1


def test_keeps_all_jobs_above_former_max_jobs_cap(tmp_path, monkeypatch):
    mod = _load_fetch()
    _prepare(monkeypatch, mod)
    root = _write_repo(tmp_path, terms=1)
    payload = _sample_payload()
    jobs = []
    for idx in range(7):
        row = json.loads(json.dumps(payload["jobs_results"][0]))
        row["job_id"] = f"unique-job-id-{idx}"
        row["via"] = f"Board {idx}"
        row["title"] = f"Role {idx}"
        jobs.append(row)
    payload["jobs_results"] = jobs
    _mock_urlopen(monkeypatch, mod, account=_account(6), search_payloads=[payload])

    assert mod.main(["--repo-root", str(root), "--date", "2026-01-31"]) == 0
    out = json.loads(
        (root / ".ai" / "history" / "job-search" / "serpapi" / "src" / "2026-01-31" / "jobs.json").read_text(
            encoding="utf-8"
        )
    )
    assert len(out["jobs"]) == 7


def _write_prior_active(root: Path, *, day: str = "2026-01-30") -> Path:
    prior_dir = root / ".ai" / "history" / "job-search" / "serpapi" / "src" / day
    prior_dir.mkdir(parents=True, exist_ok=True)
    path = prior_dir / "jobs.json"
    path.write_text(
        json.dumps(
            {
                "platform": "serpapi",
                "pulled_at": f"{day}T12:00:00Z",
                "jobs": [
                    {
                        "id": "serpapi:prior:111",
                        "status": "active",
                        "status_updated_at": f"{day}T12:00:00Z",
                        "title": "Prior Role",
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _assert_prior_still_active(prior_path: Path, today_path: Path, captured: str) -> None:
    prior = json.loads(prior_path.read_text(encoding="utf-8"))
    assert prior["jobs"][0]["id"] == "serpapi:prior:111"
    assert prior["jobs"][0]["status"] == "active"
    assert prior["jobs"][0]["status_updated_at"] == "2026-01-30T12:00:00Z"
    today = json.loads(today_path.read_text(encoding="utf-8"))
    assert "serpapi:prior:111" not in {job["id"] for job in today["jobs"]}
    assert "Closed: 0" in captured
    assert "SUMMARY" in captured and "closed=0" in captured


def test_prior_id_absent_from_today_stays_active(tmp_path, monkeypatch, capsys):
    mod = _load_fetch()
    _prepare(monkeypatch, mod)
    root = _write_repo(tmp_path, terms=1)
    prior_path = _write_prior_active(root)
    _mock_urlopen(monkeypatch, mod, account=_account(6), search_payloads=[_sample_payload()])

    assert mod.main(["--repo-root", str(root), "--date", "2026-01-31"]) == 0
    today_path = root / ".ai" / "history" / "job-search" / "serpapi" / "src" / "2026-01-31" / "jobs.json"
    _assert_prior_still_active(prior_path, today_path, capsys.readouterr().out)


def test_rebuild_does_not_close_absent_prior_ids(tmp_path, monkeypatch, capsys):
    mod = _load_fetch()
    _prepare(monkeypatch, mod)
    root = _write_repo(tmp_path, terms=1)
    prior_path = _write_prior_active(root)
    _mock_urlopen(monkeypatch, mod, account=_account(6), search_payloads=[_sample_payload()])

    assert mod.main(["--repo-root", str(root), "--date", "2026-01-31", "--rebuild"]) == 0
    today_path = root / ".ai" / "history" / "job-search" / "serpapi" / "src" / "2026-01-31" / "jobs.json"
    _assert_prior_still_active(prior_path, today_path, capsys.readouterr().out)


def test_missing_max_searches_fails_closed(tmp_path, monkeypatch):
    mod = _load_fetch()
    _prepare(monkeypatch, mod)
    root = _write_repo(tmp_path)
    criteria_path = root / ".ai" / "guardrails" / "locked-job-search-criteria.json"
    payload = json.loads(criteria_path.read_text(encoding="utf-8"))
    del payload["criteria"][1]["max_searches"]
    criteria_path.write_text(json.dumps(payload), encoding="utf-8")

    assert mod.main(["--repo-root", str(root), "--date", "2026-01-31"]) == 1


