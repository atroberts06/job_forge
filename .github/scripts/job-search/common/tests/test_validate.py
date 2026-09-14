"""Validator fail-closed checks (schema + file-local semantics)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import make_envelope, make_job
from common.validate_jobs import is_utc_z, validate_file, validate_semantic
from common.validate_job_search import validate_criteria_semantic


def _write(tmp_path: Path, envelope: dict) -> Path:
    path = tmp_path / "jobs.json"
    path.write_text(json.dumps(envelope), encoding="utf-8")
    return path


def test_valid_envelope_passes(tmp_path, schema_path):
    env = make_envelope([make_job()])
    path = _write(tmp_path, env)
    assert validate_file(path, schema_path) == []


def test_duplicate_ids_fail(tmp_path, schema_path):
    env = make_envelope(
        [
            make_job(job_id="greenhouse:lts:100", source_job_id="100"),
            make_job(job_id="greenhouse:lts:100", source_job_id="100", title="Other"),
        ]
    )
    errors = validate_file(_write(tmp_path, env), schema_path)
    assert any("duplicate id" in e for e in errors)


def test_id_shape_requires_three_segments():
    env = make_envelope([make_job(job_id="greenhouse:100", source_job_id="100")])
    errors = validate_semantic(env)
    assert any("three non-empty segments" in e for e in errors)


def test_id_platform_must_match_envelope():
    env = make_envelope([make_job(job_id="lever:lts:100", source_job_id="100")])
    errors = validate_semantic(env)
    assert any("does not match envelope platform" in e for e in errors)


def test_id_trailing_segment_must_equal_source_job_id():
    env = make_envelope([make_job(job_id="greenhouse:lts:100", source_job_id="999")])
    errors = validate_semantic(env)
    assert any("does not equal source_job_id" in e for e in errors)


def test_empty_title_fails():
    env = make_envelope([make_job(title="   ")])
    errors = validate_semantic(env)
    assert any("title" in e and "non-empty" in e for e in errors)


def test_empty_company_fails():
    env = make_envelope([make_job(company="")])
    errors = validate_semantic(env)
    assert any("company" in e and "non-empty" in e for e in errors)


def test_non_utc_timestamp_rejected():
    assert is_utc_z("2026-08-11T15:03:55-04:00") is False
    assert is_utc_z("2026-08-11T19:03:55Z") is True
    env = make_envelope(
        [make_job(status_updated_at="2026-08-11T15:03:55-04:00")],
        pulled_at="2026-08-11T15:03:55-04:00",
    )
    errors = validate_semantic(env)
    assert any("status_updated_at" in e and "UTC" in e for e in errors)
    assert any("pulled_at" in e and "UTC" in e for e in errors)


def test_missing_work_location_type_fails_schema(tmp_path, schema_path):
    job = make_job()
    del job["work_location_type"]
    errors = validate_file(_write(tmp_path, make_envelope([job])), schema_path)
    assert any("work_location_type" in e for e in errors)


def test_remote_boolean_rejected_as_additional_property(tmp_path, schema_path):
    job = make_job()
    job["remote"] = True
    errors = validate_file(_write(tmp_path, make_envelope([job])), schema_path)
    assert any("additional" in e.lower() or "remote" in e for e in errors)


def test_jobs_status_approved_rejected_completed_fail_schema(tmp_path, schema_path):
    for status in ("approved", "rejected", "completed"):
        sub = tmp_path / status
        sub.mkdir()
        job = make_job(status=status)
        errors = validate_file(_write(sub, make_envelope([job])), schema_path)
        assert errors, f"expected schema failure for status={status}"


def test_analysis_stub_passes(tmp_path, schema_path):
    analyses = tmp_path / "analyses"
    analyses.mkdir()
    stub = {
        "platform": "greenhouse",
        "job_id": "greenhouse:lts:100",
        "analysis_id": 0,
        "updated_at": "2026-08-11T16:00:00Z",
        "analyses": [
            {
                "analysis_id": 0,
                "job_id": "greenhouse:lts:100",
                "pull_date": "2026-08-11",
                "revision": 0,
                "is_current": True,
                "run_id": None,
                "analyzed_at": None,
                "decision": None,
                "justification": None,
                "experience": {"requirements": []},
                "skills": {"requirements": []},
                "constraints": {"requirements": []},
                "external_context": {"decision_impact": "none", "sources": []},
                "started_at": None,
                "ended_at": None,
                "tokens_in": None,
                "tokens_out": None,
                "cache_tokens_in": None,
                "thinking_tokens": None,
                "context_usage_percent": None,
                "context_metric_status": "not_programmatically_available",
            }
        ],
    }
    path = analyses / "greenhouse-lts-100-analysis.json"
    path.write_text(json.dumps(stub), encoding="utf-8")
    from common.validate_job_search import validate_file as validate_any

    errors = validate_any(path, schema_path, repo_root=None, require_stub=True)
    assert errors == []


def test_leftover_schema_version_on_pull_file_fails(tmp_path, schema_path):
    env = make_envelope([make_job()])
    env["schema_version"] = "1.1"
    errors = validate_file(_write(tmp_path, env), schema_path)
    assert any("schema_version" in e for e in errors)


def test_jsc_002_requires_max_searches_integer():
    errors = validate_criteria_semantic(
        {
            "criteria": [
                {"id": "jsc_001", "pipeline": "greenhouse"},
                {"id": "jsc_002", "pipeline": "google_jobs"},
            ]
        }
    )
    assert any("max_searches" in e for e in errors)


def test_jsc_001_rejects_max_searches():
    errors = validate_criteria_semantic(
        {
            "criteria": [
                {"id": "jsc_001", "pipeline": "greenhouse", "max_searches": 6},
            ]
        }
    )
    assert any("Google-only" in e and "max_searches" in e for e in errors)


def test_jsc_003_requires_talentbrew_pipeline_and_knobs():
    errors = validate_criteria_semantic(
        {
            "criteria": [
                {"id": "jsc_001", "pipeline": "greenhouse"},
                {"id": "jsc_003", "pipeline": "google_jobs", "keywords": []},
            ]
        }
    )
    assert any("pipeline must be 'talentbrew'" in e for e in errors)
    assert any("keywords" in e for e in errors)


def test_talentbrew_requires_workday_requisition_id(tmp_path, schema_path):
    job = make_job(job_id="talentbrew:capital-one:100", source_job_id="100")
    errors = validate_file(_write(tmp_path, make_envelope([job], platform="talentbrew")), schema_path)
    assert any("workday_requisition_id" in e for e in errors)


def test_talentbrew_accepts_workday_requisition_id(tmp_path, schema_path):
    job = make_job(job_id="talentbrew:capital-one:100", source_job_id="100")
    job["workday_requisition_id"] = "R244159"
    errors = validate_file(_write(tmp_path, make_envelope([job], platform="talentbrew")), schema_path)
    assert errors == []


def test_greenhouse_omitting_workday_requisition_id_still_passes(tmp_path, schema_path):
    errors = validate_file(_write(tmp_path, make_envelope([make_job()])), schema_path)
    assert errors == []
