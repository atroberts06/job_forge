"""I8 sidecar and approved-queue acceptance cases (G7)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from conftest import FIXTURES, make_envelope, make_job, write_day
from common.validate_job_search import validate_file
from common.validate_jobs import validate_file as validate_jobs_file

ANALYSIS_DIR = FIXTURES / "analysis"


def _load(name: str) -> dict:
    return json.loads((ANALYSIS_DIR / name).read_text(encoding="utf-8"))


def _write_analysis(tmp_path: Path, doc: dict, filename: str = "greenhouse-lts-100-analysis.json") -> Path:
    analyses = tmp_path / "analyses"
    analyses.mkdir(parents=True, exist_ok=True)
    path = analyses / filename
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def _repo_with_job(tmp_path: Path, *, status: str = "new", day: str = "2026-08-11") -> Path:
    src = tmp_path / ".ai" / "history" / "job-search" / "greenhouse" / "src"
    write_day(src, day, [make_job(status=status)])
    return tmp_path


def test_valid_stub_0_0(tmp_path, schema_path):
    path = _write_analysis(tmp_path, _load("stub-greenhouse-lts-100-analysis.json"))
    assert validate_file(path, schema_path, repo_root=None, require_stub=True) == []


def test_valid_first_fill_1_1(tmp_path, schema_path):
    root = _repo_with_job(tmp_path)
    path = _write_analysis(tmp_path, _load("first-fill-greenhouse-lts-100-analysis.json"))
    assert validate_file(path, schema_path, repo_root=root, require_stub=False) == []


def test_duplicate_analysis_id_fails(tmp_path, schema_path):
    doc = _load("first-fill-greenhouse-lts-100-analysis.json")
    extra = copy.deepcopy(doc["analyses"][0])
    extra["is_current"] = False
    extra["revision"] = 2
    doc["analyses"].append(extra)
    errors = validate_file(_write_analysis(tmp_path, doc), schema_path, repo_root=None)
    assert any("duplicate" in e for e in errors)


def test_two_is_current_fails(tmp_path, schema_path):
    doc = _load("first-fill-greenhouse-lts-100-analysis.json")
    extra = copy.deepcopy(doc["analyses"][0])
    extra["analysis_id"] = 2
    extra["is_current"] = True
    doc["analyses"].append(extra)
    errors = validate_file(_write_analysis(tmp_path, doc), schema_path, repo_root=None)
    assert any("exactly one row must have is_current true" in e for e in errors)


def test_envelope_fk_mismatch_fails(tmp_path, schema_path):
    doc = _load("first-fill-greenhouse-lts-100-analysis.json")
    doc["analysis_id"] = 99
    errors = validate_file(_write_analysis(tmp_path, doc), schema_path, repo_root=None)
    assert any("must equal is_current row" in e for e in errors)


def test_revision_0_after_fill_fails(tmp_path, schema_path):
    doc = _load("first-fill-greenhouse-lts-100-analysis.json")
    doc["analyses"][0]["revision"] = 0
    errors = validate_file(_write_analysis(tmp_path, doc), schema_path, repo_root=None)
    assert any("must not remain 0 after fill" in e for e in errors)


def test_decision_impact_not_none_fails(tmp_path, schema_path):
    doc = _load("first-fill-greenhouse-lts-100-analysis.json")
    doc["analyses"][0]["external_context"]["decision_impact"] = "used"
    errors = validate_file(_write_analysis(tmp_path, doc), schema_path, repo_root=None)
    assert errors
    assert any("decision_impact" in e for e in errors)


def test_missing_telemetry_keys_fail(tmp_path, schema_path):
    doc = _load("first-fill-greenhouse-lts-100-analysis.json")
    del doc["analyses"][0]["tokens_in"]
    errors = validate_file(_write_analysis(tmp_path, doc), schema_path, repo_root=None)
    assert any("tokens_in" in e for e in errors)


def test_null_context_metric_status_fails(tmp_path, schema_path):
    doc = _load("first-fill-greenhouse-lts-100-analysis.json")
    doc["analyses"][0]["context_metric_status"] = None
    errors = validate_file(_write_analysis(tmp_path, doc), schema_path, repo_root=None)
    assert any("context_metric_status" in e for e in errors)


def test_g5_status_mismatch_is_not_a_fail(tmp_path, schema_path):
    root = _repo_with_job(tmp_path, status="new")
    path = _write_analysis(tmp_path, _load("first-fill-greenhouse-lts-100-analysis.json"))
    assert validate_file(path, schema_path, repo_root=root) == []
    jobs_path = root / ".ai" / "history" / "job-search" / "greenhouse" / "src" / "2026-08-11" / "jobs.json"
    assert validate_jobs_file(jobs_path, schema_path) == []


def test_missing_sidecar_is_not_a_jobs_json_fail(tmp_path, schema_path):
    src = tmp_path / "src"
    jobs_path = write_day(src, "2026-08-11", [make_job()])
    assert validate_jobs_file(jobs_path, schema_path) == []


def test_closed_id_on_prior_jobs_json_passes(tmp_path, schema_path):
    root = _repo_with_job(tmp_path, status="closed", day="2026-08-10")
    path = _write_analysis(tmp_path, _load("first-fill-greenhouse-lts-100-analysis.json"))
    assert validate_file(path, schema_path, repo_root=root) == []


def test_queue_analysis_id_missing_from_sidecar_fails(tmp_path, schema_path):
    platform = tmp_path / "greenhouse"
    analyses = platform / "analyses"
    analyses.mkdir(parents=True)
    sidecar = _load("first-fill-greenhouse-lts-100-analysis.json")
    (analyses / "greenhouse-lts-100-analysis.json").write_text(json.dumps(sidecar), encoding="utf-8")
    approved = {
        "platform": "greenhouse",
        "jobs": [
                    {
                        "id": "greenhouse:lts:100",
                        "analysis_id": 99,
                        "approved_at": "2026-08-19T18:00:00Z",
                        "status": "approved",
                        "status_updated_at": "2026-08-19T18:00:00Z",
                        "started_at": None,
                        "attempt_count": None,
                        "completed_at": None,
                        "pr_url": None,
                        "pr_number": None,
                        "sandbox_path": None,
                        "feature_branch": None,
                    }
        ],
    }
    path = platform / "approved-jobs.json"
    path.write_text(json.dumps(approved), encoding="utf-8")
    errors = validate_file(path, schema_path, repo_root=None)
    assert any("not present in sidecar" in e for e in errors)


def test_queue_analysis_id_present_passes(tmp_path, schema_path):
    root = _repo_with_job(tmp_path)
    platform = root / ".ai" / "history" / "job-search" / "greenhouse"
    analyses = platform / "analyses"
    analyses.mkdir(parents=True, exist_ok=True)
    sidecar = _load("first-fill-greenhouse-lts-100-analysis.json")
    (analyses / "greenhouse-lts-100-analysis.json").write_text(json.dumps(sidecar), encoding="utf-8")
    approved = {
        "platform": "greenhouse",
        "jobs": [
                    {
                        "id": "greenhouse:lts:100",
                        "analysis_id": 1,
                        "approved_at": "2026-08-19T18:00:00Z",
                        "status": "approved",
                        "status_updated_at": "2026-08-19T18:00:00Z",
                        "started_at": None,
                        "attempt_count": None,
                        "completed_at": None,
                        "pr_url": None,
                        "pr_number": None,
                        "sandbox_path": None,
                        "feature_branch": None,
                    }
        ],
    }
    path = platform / "approved-jobs.json"
    path.write_text(json.dumps(approved), encoding="utf-8")
    assert validate_file(path, schema_path, repo_root=root) == []


CORE_THEMES = {
    "job_skill_1": "Salesforce Education Cloud",
    "job_skill_2": "Systems Integration",
    "job_skill_3": "Cloud Strategy",
    "strength_1": "Enterprise Architecture Governance",
    "strength_2": "Cross-functional Team Leadership",
    "strength_3": "End-to-End Migration Execution",
    "opening_hook": "I bring Salesforce architecture leadership to LTS.",
}


def test_core_themes_on_first_fill_validates(tmp_path, schema_path):
    root = _repo_with_job(tmp_path)
    doc = _load("first-fill-greenhouse-lts-100-analysis.json")
    doc["analyses"][0]["core_themes"] = CORE_THEMES
    path = _write_analysis(tmp_path, doc)
    assert validate_file(path, schema_path, repo_root=root, require_stub=False) == []


def test_core_themes_extra_key_fails(tmp_path, schema_path):
    doc = _load("first-fill-greenhouse-lts-100-analysis.json")
    extra = dict(CORE_THEMES)
    extra["job_skill_4"] = "Invented"
    doc["analyses"][0]["core_themes"] = extra
    errors = validate_file(_write_analysis(tmp_path, doc), schema_path, repo_root=None)
    assert errors
