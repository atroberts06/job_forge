"""R3 same-day merge dedupe + R4 lookback/rebuild (offline, no live API)."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from conftest import make_job, make_raw_greenhouse, write_day
from greenhouse.fetch_greenhouse_jobs import main, merge_jobs, prior_job_ids, utc_today


TODAY = date(2026, 8, 11)


def _run_main(repo_root: Path, *, rebuild: bool = False, pull_date: str | None = None, raw_jobs=None):
    raw_jobs = raw_jobs if raw_jobs is not None else []
    argv = ["--repo-root", str(repo_root)]
    if pull_date:
        argv.extend(["--date", pull_date])
    if rebuild:
        argv.append("--rebuild")

    with (
        patch("greenhouse.fetch_greenhouse_jobs.utc_today", return_value=TODAY),
        patch("greenhouse.fetch_greenhouse_jobs.fetch_board_jobs", return_value=raw_jobs),
        patch("greenhouse.fetch_greenhouse_jobs.now_iso", return_value="2026-08-11T16:00:00Z"),
        patch("common.clock.now_iso", return_value="2026-08-11T16:00:00Z"),
    ):
        return main(argv)


def _load_day(src: Path, day: str) -> dict:
    return json.loads((src / day / "jobs.json").read_text(encoding="utf-8"))


# --- R3 cases 1–6 ---


def test_r3_1_first_pull_of_day_creates_file(repo_layout):
    root, src = repo_layout["root"], repo_layout["src"]
    raw = [make_raw_greenhouse(job_id=100, location_name="New York, NY")]
    assert _run_main(root, pull_date="2026-08-11", raw_jobs=raw) == 0
    data = _load_day(src, "2026-08-11")
    assert len(data["jobs"]) == 1
    assert data["jobs"][0]["id"] == "greenhouse:lts:100"
    assert "schema_version" not in data
    assert data["pulled_at"].endswith("Z")


def test_r3_2_second_pull_overlapping_ids_preserves_row(repo_layout):
    root, src = repo_layout["root"], repo_layout["src"]
    original = make_job(
        job_id="greenhouse:lts:100",
        source_job_id="100",
        status="new",
        status_updated_at="2026-08-11T10:00:00Z",
        location="New York, NY",
    )
    write_day(src, "2026-08-11", [original], pulled_at="2026-08-11T10:00:00Z")
    raw = [make_raw_greenhouse(job_id=100, location_name="New York, NY - Remote")]
    assert _run_main(root, pull_date="2026-08-11", raw_jobs=raw) == 0
    data = _load_day(src, "2026-08-11")
    assert len(data["jobs"]) == 1
    row = data["jobs"][0]
    assert row["status"] == "new"
    assert row["status_updated_at"] == "2026-08-11T10:00:00Z"
    assert row["location"] == "New York, NY"  # original immutable
    assert data["pulled_at"] == "2026-08-11T16:00:00Z"


def test_r3_3_second_pull_appends_new_id(repo_layout):
    root, src = repo_layout["root"], repo_layout["src"]
    existing = make_job(job_id="greenhouse:lts:100", source_job_id="100")
    write_day(src, "2026-08-11", [existing])
    raw = [
        make_raw_greenhouse(job_id=100, location_name="New York, NY"),
        make_raw_greenhouse(job_id=200, title="Enterprise Architect", location_name="NJ"),
    ]
    assert _run_main(root, pull_date="2026-08-11", raw_jobs=raw) == 0
    data = _load_day(src, "2026-08-11")
    ids = {j["id"] for j in data["jobs"]}
    assert ids == {"greenhouse:lts:100", "greenhouse:lts:200"}
    a = next(j for j in data["jobs"] if j["id"] == "greenhouse:lts:100")
    assert a["status_updated_at"] == existing["status_updated_at"]


def test_r3_4_second_pull_empty_fetch_keeps_existing(repo_layout):
    root, src = repo_layout["root"], repo_layout["src"]
    existing = make_job(job_id="greenhouse:lts:100", source_job_id="100")
    write_day(src, "2026-08-11", [existing], pulled_at="2026-08-11T10:00:00Z")
    assert _run_main(root, pull_date="2026-08-11", raw_jobs=[]) == 0
    data = _load_day(src, "2026-08-11")
    assert len(data["jobs"]) == 1
    assert data["jobs"][0]["id"] == "greenhouse:lts:100"
    assert data["pulled_at"] == "2026-08-11T16:00:00Z"


def test_r3_5_idempotent_rerun_no_duplicates(repo_layout):
    root, src = repo_layout["root"], repo_layout["src"]
    raw = [make_raw_greenhouse(job_id=100, location_name="New York, NY")]
    assert _run_main(root, pull_date="2026-08-11", raw_jobs=raw) == 0
    assert _run_main(root, pull_date="2026-08-11", raw_jobs=raw) == 0
    data = _load_day(src, "2026-08-11")
    assert len(data["jobs"]) == 1


def test_r3_6_intra_fetch_duplicate_first_wins():
    a = make_job(job_id="greenhouse:lts:100", source_job_id="100", title="First")
    b = make_job(job_id="greenhouse:lts:100", source_job_id="100", title="Second")
    merged, appended = merge_jobs([], [a, b])
    assert len(merged) == 1
    assert merged[0]["title"] == "First"
    assert appended == 1


# --- R4 cases ---


def test_r4_1_no_prior_file_all_new(repo_layout):
    root, src = repo_layout["root"], repo_layout["src"]
    raw = [make_raw_greenhouse(job_id=100, location_name="New York, NY")]
    assert _run_main(root, pull_date="2026-08-11", raw_jobs=raw) == 0
    assert _load_day(src, "2026-08-11")["jobs"][0]["status"] == "new"


def test_r4_2_nearest_prior_marks_active_and_new(repo_layout):
    root, src = repo_layout["root"], repo_layout["src"]
    write_day(
        src,
        "2026-08-10",
        [
            make_job(
                job_id="greenhouse:lts:100",
                source_job_id="100",
                status="new",
                pulled_at="2026-08-10",
                status_updated_at="2026-08-10T12:00:00Z",
            )
        ],
    )
    raw = [
        make_raw_greenhouse(job_id=100, location_name="New York, NY"),
        make_raw_greenhouse(job_id=200, title="Enterprise Architect", location_name="NJ"),
    ]
    assert _run_main(root, pull_date="2026-08-11", raw_jobs=raw) == 0
    by_id = {j["id"]: j for j in _load_day(src, "2026-08-11")["jobs"]}
    assert by_id["greenhouse:lts:100"]["status"] == "active"
    assert by_id["greenhouse:lts:100"]["status_updated_at"] == "2026-08-11T16:00:00Z"
    assert by_id["greenhouse:lts:200"]["status"] == "new"


def test_r4_2b_active_to_active_copies_status_updated_at(repo_layout):
    root, src = repo_layout["root"], repo_layout["src"]
    write_day(
        src,
        "2026-08-10",
        [
            make_job(
                job_id="greenhouse:lts:100",
                source_job_id="100",
                status="active",
                pulled_at="2026-08-10",
                status_updated_at="2026-08-09T08:00:00Z",
            )
        ],
    )
    raw = [make_raw_greenhouse(job_id=100, location_name="New York, NY")]
    assert _run_main(root, pull_date="2026-08-11", raw_jobs=raw) == 0
    row = _load_day(src, "2026-08-11")["jobs"][0]
    assert row["status"] == "active"
    assert row["status_updated_at"] == "2026-08-09T08:00:00Z"


def test_r4_3_gap_days_nearest_prior_within_30(repo_layout):
    src = repo_layout["src"]
    write_day(
        src,
        "2026-08-08",
        [make_job(job_id="greenhouse:lts:100", source_job_id="100", pulled_at="2026-08-08")],
    )
    ids = prior_job_ids(src, TODAY)
    assert ids == {"greenhouse:lts:100"}


def test_r4_4_merge_append_active_preserves_existing_new(repo_layout):
    root, src = repo_layout["root"], repo_layout["src"]
    existing = make_job(
        job_id="greenhouse:lts:100",
        source_job_id="100",
        status="new",
        status_updated_at="2026-08-11T09:00:00Z",
    )
    write_day(src, "2026-08-11", [existing], pulled_at="2026-08-11T09:00:00Z")
    write_day(
        src,
        "2026-08-10",
        [make_job(job_id="greenhouse:lts:200", source_job_id="200", pulled_at="2026-08-10")],
    )
    raw = [
        make_raw_greenhouse(job_id=100, location_name="New York, NY"),
        make_raw_greenhouse(job_id=200, title="Enterprise Architect", location_name="NJ"),
    ]
    assert _run_main(root, pull_date="2026-08-11", raw_jobs=raw) == 0
    by_id = {j["id"]: j for j in _load_day(src, "2026-08-11")["jobs"]}
    assert by_id["greenhouse:lts:100"]["status"] == "new"
    assert by_id["greenhouse:lts:100"]["status_updated_at"] == "2026-08-11T09:00:00Z"
    assert by_id["greenhouse:lts:200"]["status"] == "active"


def test_r4_5_rebuild_today_all_new_no_lookback(repo_layout):
    root, src = repo_layout["root"], repo_layout["src"]
    write_day(
        src,
        "2026-08-10",
        [make_job(job_id="greenhouse:lts:100", source_job_id="100", pulled_at="2026-08-10")],
    )
    write_day(
        src,
        "2026-08-11",
        [
            make_job(
                job_id="greenhouse:lts:100",
                source_job_id="100",
                status="active",
                status_updated_at="2026-08-11T08:00:00Z",
            )
        ],
    )
    raw = [make_raw_greenhouse(job_id=100, location_name="New York, NY")]
    assert _run_main(root, pull_date="2026-08-11", rebuild=True, raw_jobs=raw) == 0
    data = _load_day(src, "2026-08-11")
    assert len(data["jobs"]) == 1
    assert data["jobs"][0]["status"] == "new"
    # 100 is still in today, so the prior row is not closed
    prior = _load_day(src, "2026-08-10")
    assert prior["jobs"][0]["status"] != "closed"


def test_r4_6_rebuild_past_date_rejected(repo_layout):
    root, src = repo_layout["root"], repo_layout["src"]
    assert _run_main(root, pull_date="2026-08-10", rebuild=True, raw_jobs=[]) == 1
    assert not (src / "2026-08-10" / "jobs.json").exists()


def test_r4_7_out_of_window_prior_treated_as_no_prior(repo_layout):
    src = repo_layout["src"]
    old = TODAY - timedelta(days=31)
    write_day(
        src,
        old,
        [make_job(job_id="greenhouse:lts:100", source_job_id="100", pulled_at=old.isoformat())],
    )
    assert prior_job_ids(src, TODAY) == set()


def test_past_date_merge_rejected(repo_layout):
    root = repo_layout["root"]
    assert _run_main(root, pull_date="2026-08-10", raw_jobs=[]) == 1


def test_close_missing_prior_id_absent_from_today(repo_layout):
    root, src = repo_layout["root"], repo_layout["src"]
    write_day(
        src,
        "2026-08-10",
        [
            make_job(job_id="greenhouse:lts:100", source_job_id="100", pulled_at="2026-08-10"),
            make_job(
                job_id="greenhouse:lts:200",
                source_job_id="200",
                title="Enterprise Architect",
                pulled_at="2026-08-10",
                status_updated_at="2026-08-10T12:00:00Z",
            ),
        ],
    )
    raw = [make_raw_greenhouse(job_id=100, location_name="New York, NY")]
    assert _run_main(root, pull_date="2026-08-11", raw_jobs=raw) == 0
    today_ids = {j["id"] for j in _load_day(src, "2026-08-11")["jobs"]}
    assert today_ids == {"greenhouse:lts:100"}
    prior = {j["id"]: j for j in _load_day(src, "2026-08-10")["jobs"]}
    assert prior["greenhouse:lts:100"]["status"] != "closed"
    assert prior["greenhouse:lts:200"]["status"] == "closed"
    assert prior["greenhouse:lts:200"]["status_updated_at"] == "2026-08-11T16:00:00Z"


def test_close_missing_id_still_present_unchanged(repo_layout):
    root, src = repo_layout["root"], repo_layout["src"]
    write_day(
        src,
        "2026-08-10",
        [
            make_job(
                job_id="greenhouse:lts:100",
                source_job_id="100",
                status="new",
                pulled_at="2026-08-10",
                status_updated_at="2026-08-10T12:00:00Z",
            )
        ],
        pulled_at="2026-08-10T12:00:00Z",
    )
    raw = [make_raw_greenhouse(job_id=100, location_name="New York, NY")]
    assert _run_main(root, pull_date="2026-08-11", raw_jobs=raw) == 0
    prior = _load_day(src, "2026-08-10")["jobs"][0]
    assert prior["status"] == "new"
    assert prior["status_updated_at"] == "2026-08-10T12:00:00Z"


def test_close_missing_no_prior_file(repo_layout):
    root, src = repo_layout["root"], repo_layout["src"]
    raw = [make_raw_greenhouse(job_id=100, location_name="New York, NY")]
    assert _run_main(root, pull_date="2026-08-11", raw_jobs=raw) == 0
    assert (src / "2026-08-11" / "jobs.json").is_file()
    assert not (src / "2026-08-10" / "jobs.json").exists()


def test_close_missing_already_closed_noop(repo_layout):
    root, src = repo_layout["root"], repo_layout["src"]
    write_day(
        src,
        "2026-08-10",
        [
            make_job(job_id="greenhouse:lts:100", source_job_id="100", pulled_at="2026-08-10"),
            make_job(
                job_id="greenhouse:lts:200",
                source_job_id="200",
                title="Enterprise Architect",
                status="closed",
                pulled_at="2026-08-10",
                status_updated_at="2026-08-10T09:00:00Z",
            ),
        ],
    )
    raw = [make_raw_greenhouse(job_id=100, location_name="New York, NY")]
    assert _run_main(root, pull_date="2026-08-11", raw_jobs=raw) == 0
    prior = {j["id"]: j for j in _load_day(src, "2026-08-10")["jobs"]}
    assert prior["greenhouse:lts:200"]["status"] == "closed"
    assert prior["greenhouse:lts:200"]["status_updated_at"] == "2026-08-10T09:00:00Z"


def test_close_missing_rebuild_closes_absent_prior_ids(repo_layout):
    root, src = repo_layout["root"], repo_layout["src"]
    write_day(
        src,
        "2026-08-10",
        [
            make_job(job_id="greenhouse:lts:100", source_job_id="100", pulled_at="2026-08-10"),
            make_job(
                job_id="greenhouse:lts:200",
                source_job_id="200",
                title="Enterprise Architect",
                pulled_at="2026-08-10",
                status_updated_at="2026-08-10T12:00:00Z",
            ),
        ],
    )
    raw = [make_raw_greenhouse(job_id=100, location_name="New York, NY")]
    assert _run_main(root, pull_date="2026-08-11", rebuild=True, raw_jobs=raw) == 0
    today = _load_day(src, "2026-08-11")
    assert len(today["jobs"]) == 1
    assert today["jobs"][0]["status"] == "new"
    prior = {j["id"]: j for j in _load_day(src, "2026-08-10")["jobs"]}
    assert prior["greenhouse:lts:100"]["status"] != "closed"
    assert prior["greenhouse:lts:200"]["status"] == "closed"
    assert prior["greenhouse:lts:200"]["status_updated_at"] == "2026-08-11T16:00:00Z"
