"""Pull-time analysis stub create-if-not-exists and --rebuild wipe."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from conftest import make_job, write_day
from common.write_analysis_stubs import main

POST_HANDOFF = ("in_progress", "failed", "completed", "deployed")


TODAY = date(2026, 8, 11)


def _run(repo_root: Path, *, rebuild: bool = False, pull_date: str = "2026-08-11") -> int:
    argv = ["--repo-root", str(repo_root), "--date", pull_date]
    if rebuild:
        argv.append("--rebuild")
    with patch("common.write_analysis_stubs.utc_today", return_value=TODAY), patch(
        "common.write_analysis_stubs.now_iso", return_value="2026-08-11T16:00:00Z"
    ):
        return main(argv)


def test_create_if_not_exists_writes_stub(repo_layout):
    root, src, platform = repo_layout["root"], repo_layout["src"], repo_layout["platform"]
    write_day(src, "2026-08-11", [make_job()])
    assert _run(root) == 0
    stub = platform / "analyses" / "greenhouse-lts-100-analysis.json"
    data = json.loads(stub.read_text(encoding="utf-8"))
    assert data["analysis_id"] == 0
    assert data["analyses"][0]["revision"] == 0
    assert data["analyses"][0]["run_id"] is None
    assert data["analyses"][0]["tokens_in"] is None
    assert data["analyses"][0]["context_metric_status"] == "not_programmatically_available"
    assert data["job_id"] == "greenhouse:lts:100"


def test_create_if_not_exists_does_not_overwrite(repo_layout):
    root, src, platform = repo_layout["root"], repo_layout["src"], repo_layout["platform"]
    write_day(src, "2026-08-11", [make_job()])
    assert _run(root) == 0
    stub = platform / "analyses" / "greenhouse-lts-100-analysis.json"
    payload = json.loads(stub.read_text(encoding="utf-8"))
    payload["analyses"][0]["justification"] = "filled"
    payload["analyses"][0]["revision"] = 1
    payload["analyses"][0]["analysis_id"] = 1
    payload["analysis_id"] = 1
    stub.write_text(json.dumps(payload), encoding="utf-8")
    assert _run(root) == 0
    data = json.loads(stub.read_text(encoding="utf-8"))
    assert data["analysis_id"] == 1
    assert data["analyses"][0]["justification"] == "filled"


def test_missing_approved_envelope_created(repo_layout):
    root, src, platform = repo_layout["root"], repo_layout["src"], repo_layout["platform"]
    write_day(src, "2026-08-11", [make_job()])
    approved = platform / "approved-jobs.json"
    assert not approved.exists()
    assert _run(root) == 0
    data = json.loads(approved.read_text(encoding="utf-8"))
    assert data["jobs"] == []
    assert "schema_version" not in data


def test_existing_approved_envelope_not_rewritten(repo_layout):
    root, src, platform = repo_layout["root"], repo_layout["src"], repo_layout["platform"]
    write_day(src, "2026-08-11", [make_job()])
    approved = platform / "approved-jobs.json"
    original = {"platform": "greenhouse", "jobs": []}
    approved.write_text(json.dumps(original) + "\nkeep-me", encoding="utf-8")
    # invalid trailing text would fail json load — write valid unique marker in notes via extra field is forbidden.
    approved.write_text(json.dumps(original, indent=2) + "\n", encoding="utf-8")
    before = approved.read_text(encoding="utf-8")
    assert _run(root) == 0
    assert approved.read_text(encoding="utf-8") == before


def test_rebuild_wipes_filled_sidecar_and_approved_row(repo_layout):
    root, src, platform = repo_layout["root"], repo_layout["src"], repo_layout["platform"]
    write_day(src, "2026-08-11", [make_job()])
    analyses = platform / "analyses"
    analyses.mkdir()
    filled = {
        "platform": "greenhouse",
        "job_id": "greenhouse:lts:100",
        "analysis_id": 1,
        "updated_at": "2026-08-11T10:00:00Z",
        "analyses": [
            {
                "analysis_id": 1,
                "job_id": "greenhouse:lts:100",
                "pull_date": "2026-08-11",
                "revision": 1,
                "is_current": True,
                "run_id": "abc",
                "analyzed_at": "2026-08-11T10:00:00Z",
                "decision": "approved",
                "justification": "ok",
                "experience": {"requirements": []},
                "skills": {"requirements": []},
                "constraints": {"requirements": []},
                "external_context": {"decision_impact": "none", "sources": []},
            }
        ],
    }
    (analyses / "greenhouse-lts-100-analysis.json").write_text(json.dumps(filled), encoding="utf-8")
    orphan = dict(filled)
    orphan["job_id"] = "greenhouse:lts:999"
    orphan["analyses"][0]["job_id"] = "greenhouse:lts:999"
    (analyses / "greenhouse-lts-999-analysis.json").write_text(json.dumps(orphan), encoding="utf-8")
    (platform / "approved-jobs.json").write_text(
        json.dumps(
            {
                "platform": "greenhouse",
                "jobs": [
                    {
                        "id": "greenhouse:lts:100",
                        "analysis_id": 1,
                        "approved_at": "2026-08-11T10:00:00Z",
                        "status": "approved",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    assert _run(root, rebuild=True) == 0
    data = json.loads((analyses / "greenhouse-lts-100-analysis.json").read_text(encoding="utf-8"))
    assert data["analysis_id"] == 0
    assert data["analyses"][0]["revision"] == 0
    assert (analyses / "greenhouse-lts-999-analysis.json").is_file()
    approved = json.loads((platform / "approved-jobs.json").read_text(encoding="utf-8"))
    assert approved["jobs"] == []


def test_rebuild_past_date_rejected(repo_layout):
    root, src = repo_layout["root"], repo_layout["src"]
    write_day(src, "2026-08-10", [make_job()])
    assert _run(root, rebuild=True, pull_date="2026-08-10") == 1


def _filled_sidecar(job_id: str = "greenhouse:lts:100") -> dict:
    return {
        "platform": "greenhouse",
        "job_id": job_id,
        "analysis_id": 1,
        "updated_at": "2026-08-11T10:00:00Z",
        "analyses": [
            {
                "analysis_id": 1,
                "job_id": job_id,
                "pull_date": "2026-08-11",
                "revision": 1,
                "is_current": True,
                "run_id": "abc",
                "analyzed_at": "2026-08-11T10:00:00Z",
                "decision": "approved",
                "justification": "ok",
                "experience": {"requirements": []},
                "skills": {"requirements": []},
                "constraints": {"requirements": []},
                "external_context": {"decision_impact": "none", "sources": []},
            }
        ],
    }


def _ledger_row(status: str, job_id: str = "greenhouse:lts:100") -> dict:
    row = {
        "id": job_id,
        "analysis_id": 1,
        "approved_at": "2026-08-11T10:00:00Z",
        "status": status,
        "status_updated_at": "2026-08-11T10:00:00Z",
        "started_at": None,
        "attempt_count": None,
        "completed_at": None,
        "pr_url": None,
        "pr_number": None,
        "sandbox_path": None,
        "feature_branch": None,
    }
    if status == "completed":
        row["completed_at"] = "2026-08-11T11:00:00Z"
        row["pr_url"] = "https://github.com/example/job-forge/pull/20"
        row["pr_number"] = 20
        row["sandbox_path"] = ".ai/history/resume-tailor/lts/servicenow-qa-analyst/"
        row["feature_branch"] = "feature/lts-servicenow-qa-analyst"
        row["status_updated_at"] = "2026-08-11T11:00:00Z"
        row["started_at"] = "2026-08-11T10:30:00Z"
        row["attempt_count"] = 1
    elif status == "deployed":
        row["completed_at"] = "2026-08-11T11:00:00Z"
        row["status_updated_at"] = "2026-08-11T12:00:00Z"
        row["artifacts_url"] = "https://drive.google.com/drive/folders/abc"
        row["pr_url"] = "https://github.com/example/job-forge/pull/20"
        row["pr_number"] = 20
        row["sandbox_path"] = ".ai/history/resume-tailor/lts/servicenow-qa-analyst/"
        row["feature_branch"] = "feature/lts-servicenow-qa-analyst"
        row["started_at"] = "2026-08-11T10:30:00Z"
        row["attempt_count"] = 1
    elif status == "failed":
        row["status_updated_at"] = "2026-08-11T11:00:00Z"
        row["started_at"] = "2026-08-11T10:30:00Z"
        row["attempt_count"] = 1
        row["failure"] = {
            "code": "unknown",
            "message": "boom",
            "failed_at": "2026-08-11T11:00:00Z",
            "step": "tailor_skill",
        }
    elif status == "in_progress":
        row["status_updated_at"] = "2026-08-11T10:30:00Z"
        row["started_at"] = "2026-08-11T10:30:00Z"
        row["attempt_count"] = 1
        row["sandbox_path"] = ".ai/history/resume-tailor/lts/servicenow-qa-analyst/"
        row["feature_branch"] = "feature/lts-servicenow-qa-analyst"
    return row


@pytest.mark.parametrize("status", POST_HANDOFF)
def test_rebuild_keeps_post_handoff_sidecar_and_ledger(repo_layout, status):
    root, src, platform = repo_layout["root"], repo_layout["src"], repo_layout["platform"]
    write_day(src, "2026-08-11", [make_job()])
    analyses = platform / "analyses"
    analyses.mkdir()
    stub = analyses / "greenhouse-lts-100-analysis.json"
    stub.write_text(json.dumps(_filled_sidecar()), encoding="utf-8")
    (platform / "approved-jobs.json").write_text(
        json.dumps({"platform": "greenhouse", "jobs": [_ledger_row(status)]}),
        encoding="utf-8",
    )
    before = json.loads(stub.read_text(encoding="utf-8"))
    assert _run(root, rebuild=True) == 0
    after = json.loads(stub.read_text(encoding="utf-8"))
    assert after["analysis_id"] == 1
    assert after["analyses"][0]["revision"] == 1
    assert after["analyses"][0]["justification"] == before["analyses"][0]["justification"]
    approved = json.loads((platform / "approved-jobs.json").read_text(encoding="utf-8"))
    assert len(approved["jobs"]) == 1
    assert approved["jobs"][0]["status"] == status


def test_rebuild_missing_sidecar_completed_writes_no_stub(repo_layout):
    root, src, platform = repo_layout["root"], repo_layout["src"], repo_layout["platform"]
    write_day(src, "2026-08-11", [make_job()])
    analyses = platform / "analyses"
    analyses.mkdir()
    dest = analyses / "greenhouse-lts-100-analysis.json"
    assert not dest.exists()
    (platform / "approved-jobs.json").write_text(
        json.dumps({"platform": "greenhouse", "jobs": [_ledger_row("completed")]}),
        encoding="utf-8",
    )
    assert _run(root, rebuild=True) == 0
    assert not dest.exists()
    approved = json.loads((platform / "approved-jobs.json").read_text(encoding="utf-8"))
    assert approved["jobs"][0]["status"] == "completed"
