"""claim_tailor_in_progress.py file-level pending → in_progress."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import common.claim_tailor_in_progress as claim
from conftest import make_job, write_day

NOW = "2026-08-30T18:00:00Z"
RUN = "c" * 32
JOB_ID = "greenhouse:lts:100"


def _sidecar(platform: Path, job_id: str = JOB_ID) -> None:
    analyses = platform / "analyses"
    analyses.mkdir(parents=True, exist_ok=True)
    doc = {
        "platform": "greenhouse",
        "job_id": job_id,
        "analysis_id": 1,
        "updated_at": NOW,
        "analyses": [
            {
                "analysis_id": 1,
                "job_id": job_id,
                "pull_date": "2026-08-11",
                "revision": 1,
                "is_current": True,
                "run_id": RUN,
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
    (analyses / f"{job_id.replace(':', '-')}-analysis.json").write_text(
        json.dumps(doc), encoding="utf-8"
    )


def _ledger(platform: Path, jobs: list[dict]) -> Path:
    path = platform / "approved-jobs.json"
    path.write_text(
        json.dumps({"platform": "greenhouse", "jobs": jobs}, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def _queue(root: Path, jobs: list[dict], *, platform: str | None = "greenhouse") -> Path:
    queue_dir = root / ".ai" / "history" / "resume-tailor" / "queue"
    queue_dir.mkdir(parents=True, exist_ok=True)
    path = queue_dir / f"{RUN}-tailor-request.json"
    payload: dict = {
        "run_id": RUN,
        "batch_number": 1,
        "created_date": "2026-08-30",
        "jobs": jobs,
    }
    if platform is not None:
        payload["platform"] = platform
    path.write_text(
        json.dumps(payload, indent=2)
        + "\n",
        encoding="utf-8",
    )
    return path


def _pending_row() -> dict:
    return {
        "id": JOB_ID,
        "status": "pending",
        "company": "LTS",
        "title": "Solution Architect",
        "location": "New York, NY",
        "url": "https://job-boards.greenhouse.io/lts/jobs/100",
        "description_text": "Architect role",
        "decision": "approved",
        "justification": "ok",
        "unmet_mandatory": [],
        "mentioned_skills": [],
    }


def _run(root: Path, queue: Path) -> tuple[int, str]:
    argv = ["--repo-root", str(root), "--queue-file", str(queue)]
    buf = StringIO()
    with patch.object(claim, "utc_now", return_value=NOW):
        old_out, old_err = __import__("sys").stdout, __import__("sys").stderr
        try:
            __import__("sys").stdout = buf
            __import__("sys").stderr = buf
            code = claim.main(argv)
        finally:
            __import__("sys").stdout = old_out
            __import__("sys").stderr = old_err
    return code, buf.getvalue()


def test_claims_pending_as_in_progress(repo_layout):
    root = repo_layout["root"]
    platform = repo_layout["platform"]
    write_day(repo_layout["src"], "2026-08-11", [make_job(job_id=JOB_ID)])
    _sidecar(platform)
    _ledger(
        platform,
        [
            {
                "id": JOB_ID,
                "analysis_id": 1,
                "approved_at": "2026-08-30T12:00:00Z",
                "status": "approved",
                "status_updated_at": "2026-08-30T12:00:00Z",
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
    queue = _queue(root, [_pending_row()])
    code, _ = _run(root, queue)
    assert code == 0
    row = json.loads((platform / "approved-jobs.json").read_text(encoding="utf-8"))["jobs"][0]
    assert row["status"] == "in_progress"
    assert row["status_updated_at"] == NOW
    assert row["started_at"] is None
    assert row["attempt_count"] is None


def test_claim_missing_ledger_fail_closed(repo_layout):
    root = repo_layout["root"]
    platform = repo_layout["platform"]
    write_day(repo_layout["src"], "2026-08-11", [make_job(job_id=JOB_ID)])
    _sidecar(platform)
    _ledger(platform, [])
    queue = _queue(root, [_pending_row()])
    code, out = _run(root, queue)
    assert code == 1
    assert "ledger row missing" in out


def test_missing_platform_fail_closed(repo_layout):
    root = repo_layout["root"]
    platform = repo_layout["platform"]
    write_day(repo_layout["src"], "2026-08-11", [make_job(job_id=JOB_ID)])
    _sidecar(platform)
    _ledger(
        platform,
        [
            {
                "id": JOB_ID,
                "analysis_id": 1,
                "approved_at": "2026-08-30T12:00:00Z",
                "status": "approved",
                "status_updated_at": "2026-08-30T12:00:00Z",
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
    queue = _queue(root, [_pending_row()], platform=None)
    code, out = _run(root, queue)
    assert code == 1
    assert "platform is required" in out
    row = json.loads((platform / "approved-jobs.json").read_text(encoding="utf-8"))["jobs"][0]
    assert row["status"] == "approved"
