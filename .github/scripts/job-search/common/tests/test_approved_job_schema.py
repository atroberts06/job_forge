"""Extended approvedJob golden shapes (consume, completed, failed)."""

from __future__ import annotations

import json

from conftest import make_job, write_day
from common.validate_job_search import validate_file

NOW = "2026-08-30T12:00:00Z"
JOB_ID = "greenhouse:lts:100"


def _sidecar(platform, analysis_id: int = 1) -> None:
    analyses = platform / "analyses"
    analyses.mkdir(parents=True, exist_ok=True)
    (analyses / f"{JOB_ID.replace(':', '-')}-analysis.json").write_text(
        json.dumps(
            {
                "platform": "greenhouse",
                "job_id": JOB_ID,
                "analysis_id": analysis_id,
                "updated_at": NOW,
                "analyses": [
                    {
                        "analysis_id": analysis_id,
                        "job_id": JOB_ID,
                        "pull_date": "2026-08-11",
                        "revision": 1,
                        "is_current": True,
                        "run_id": "a" * 32,
                        "analyzed_at": NOW,
                        "decision": "approved",
                        "justification": "ok",
                        "experience": {"requirements": []},
                        "skills": {"requirements": []},
                        "constraints": {"requirements": []},
                        "external_context": {"decision_impact": "none", "sources": []},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def _validate(root, platform, jobs: list[dict]) -> list[str]:
    path = platform / "approved-jobs.json"
    path.write_text(
        json.dumps({"platform": "greenhouse", "jobs": jobs}, indent=2)
        + "\n",
        encoding="utf-8",
    )
    schema = root / ".ai" / "guardrails" / "locked-job-search-data-model.json"
    return validate_file(path, schema, repo_root=root)


def test_consume_upsert_shape(repo_layout):
    root = repo_layout["root"]
    platform = repo_layout["platform"]
    write_day(repo_layout["src"], "2026-08-11", [make_job(job_id=JOB_ID)])
    _sidecar(platform)
    errors = _validate(
        root,
        platform,
        [
            {
                "id": JOB_ID,
                "analysis_id": 1,
                "approved_at": NOW,
                "status": "approved",
                "status_updated_at": NOW,
                "started_at": None,
                "attempt_count": None,
                "completed_at": None,
                "pr_url": None,
                "pr_number": None,
                "sandbox_path": None,
                "feature_branch": None,
            }
        ],
    )
    assert errors == []


def test_completed_execution_shape(repo_layout):
    root = repo_layout["root"]
    platform = repo_layout["platform"]
    write_day(repo_layout["src"], "2026-08-11", [make_job(job_id=JOB_ID)])
    _sidecar(platform)
    errors = _validate(
        root,
        platform,
        [
            {
                "id": JOB_ID,
                "analysis_id": 1,
                "approved_at": NOW,
                "status": "completed",
                "status_updated_at": NOW,
                "started_at": NOW,
                "attempt_count": 1,
                "completed_at": NOW,
                "pr_number": 42,
                "pr_url": "https://github.com/example/job-forge/pull/42",
                "sandbox_path": ".ai/history/resume-tailor/lts/solution-architect/",
                "feature_branch": "feature/lts-solution-architect",
            }
        ],
    )
    assert errors == []


def test_deployed_execution_shape(repo_layout):
    root = repo_layout["root"]
    platform = repo_layout["platform"]
    write_day(repo_layout["src"], "2026-08-11", [make_job(job_id=JOB_ID)])
    _sidecar(platform)
    errors = _validate(
        root,
        platform,
        [
            {
                "id": JOB_ID,
                "analysis_id": 1,
                "approved_at": NOW,
                "status": "deployed",
                "status_updated_at": NOW,
                "started_at": NOW,
                "attempt_count": 1,
                "completed_at": NOW,
                "pr_number": 20,
                "pr_url": "https://github.com/example/job-forge/pull/20",
                "sandbox_path": ".ai/history/resume-tailor/lts/servicenow-qa-analyst/",
                "feature_branch": "feature/lts-servicenow-qa-analyst",
                "artifacts_url": "https://drive.google.com/drive/folders/abc123",
            }
        ],
    )
    assert errors == []


def test_failed_p2e1_shape(repo_layout):
    root = repo_layout["root"]
    platform = repo_layout["platform"]
    write_day(repo_layout["src"], "2026-08-11", [make_job(job_id=JOB_ID)])
    _sidecar(platform)
    errors = _validate(
        root,
        platform,
        [
            {
                "id": JOB_ID,
                "analysis_id": 1,
                "approved_at": NOW,
                "status": "failed",
                "status_updated_at": NOW,
                "started_at": NOW,
                "attempt_count": 1,
                "completed_at": None,
                "pr_url": None,
                "pr_number": None,
                "sandbox_path": None,
                "feature_branch": None,
                "failure": {
                    "code": "collision",
                    "message": "sandbox owned by another job_id",
                    "failed_at": NOW,
                    "step": "p2-x1",
                },
            }
        ],
    )
    assert errors == []
