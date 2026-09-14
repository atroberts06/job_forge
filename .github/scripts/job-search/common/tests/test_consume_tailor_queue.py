"""consume_tailor_queue.py success, failure, drain, and collision fail-closed."""

from __future__ import annotations

import json
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import common.consume_tailor_queue as consume_tailor
from conftest import make_job, write_day

_RESUME_TAILOR = Path(__file__).resolve().parents[3] / "resume-tailor"
if str(_RESUME_TAILOR) not in sys.path:
    sys.path.insert(0, str(_RESUME_TAILOR))

from validate_tailor_request import validate_tailor_request  # noqa: E402

NOW = "2026-08-30T18:00:00Z"
RUN = "c" * 32
JOB_ID = "greenhouse:lts:100"
CORE_THEMES = {
    "job_skill_1": "Salesforce Education Cloud",
    "job_skill_2": "Systems Integration",
    "job_skill_3": "Cloud Strategy",
    "strength_1": "Enterprise Architecture Governance",
    "strength_2": "Cross-functional Team Leadership",
    "strength_3": "End-to-End Migration Execution",
    "opening_hook": "I bring Salesforce architecture leadership to LTS.",
}


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
        json.dumps({"platform": "greenhouse", "jobs": jobs}, indent=2)
        + "\n",
        encoding="utf-8",
    )
    return path


def _queue(
    root: Path,
    jobs: list[dict],
    *,
    platform: str | None = "greenhouse",
    run_id: str = RUN,
    batch_number: int = 1,
) -> Path:
    queue_dir = root / ".ai" / "history" / "resume-tailor" / "queue"
    queue_dir.mkdir(parents=True, exist_ok=True)
    path = queue_dir / f"{run_id}-tailor-request.json"
    payload: dict = {
        "run_id": run_id,
        "batch_number": batch_number,
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


def _approved_row(job_id: str = JOB_ID) -> dict:
    return {
        "id": job_id,
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


def _complete_payload(**extra) -> dict:
    row = {
        "id": JOB_ID,
        "status": "tailor_complete",
        "company": "LTS",
        "title": "Solution Architect",
        "company_slug": "lts",
        "position_slug": "solution-architect",
        "location": "New York, NY",
        "url": "https://job-boards.greenhouse.io/lts/jobs/100",
        "description_text": "Architect role",
        "decision": "approved",
        "justification": "ok",
        "unmet_mandatory": [],
        "mentioned_skills": [],
        "started_at": "2026-08-30T17:00:00Z",
        "attempt_count": 1,
        "completed_at": "2026-08-30T17:55:00Z",
        "pr_url": "https://github.com/example/job-forge/pull/99",
        "pr_number": 99,
        "sandbox_path": ".ai/history/resume-tailor/lts/solution-architect/",
        "feature_branch": "feature/lts-solution-architect",
    }
    row.update(extra)
    return row


def _failed_payload(failure: dict | None = None, **extra) -> dict:
    fail_obj = failure or {
        "code": "tailor_skill",
        "message": "skill aborted",
        "failed_at": NOW,
        "step": "step-2",
    }
    row = {
        "id": JOB_ID,
        "status": "failed",
        "company": "LTS",
        "title": "Solution Architect",
        "company_slug": "lts",
        "position_slug": "solution-architect",
        "location": "New York, NY",
        "url": "https://job-boards.greenhouse.io/lts/jobs/100",
        "description_text": "Architect role",
        "decision": "approved",
        "justification": "ok",
        "unmet_mandatory": [],
        "mentioned_skills": [],
        "started_at": "2026-08-30T17:00:00Z",
        "attempt_count": 1,
        "completed_at": None,
        "pr_url": None,
        "pr_number": None,
        "sandbox_path": None,
        "feature_branch": None,
        "failure": fail_obj,
    }
    row.update(extra)
    return row


def _run(root: Path, queue: Path | None = None, extra: list[str] | None = None) -> tuple[int, str]:
    argv = ["--repo-root", str(root)]
    if queue is not None:
        argv.extend(["--queue-file", str(queue)])
    if extra:
        argv.extend(extra)
    buf = StringIO()
    with patch.object(consume_tailor, "utc_now", return_value=NOW):
        old_out, old_err = __import__("sys").stdout, __import__("sys").stderr
        try:
            __import__("sys").stdout = buf
            __import__("sys").stderr = buf
            code = consume_tailor.main(argv)
        finally:
            __import__("sys").stdout = old_out
            __import__("sys").stderr = old_err
    return code, buf.getvalue()


def test_success_copies_completed_and_drains_queue(repo_layout):
    root = repo_layout["root"]
    platform = repo_layout["platform"]
    write_day(repo_layout["src"], "2026-08-11", [make_job(job_id=JOB_ID)])
    _sidecar(platform)
    _ledger(platform, [_approved_row()])
    queue = _queue(
        root,
        [_complete_payload()],
    )
    code, out = _run(root, queue)
    assert code == 0
    ledger = json.loads((platform / "approved-jobs.json").read_text(encoding="utf-8"))
    row = ledger["jobs"][0]
    assert row["status"] == "completed"
    assert row["pr_url"] == "https://github.com/example/job-forge/pull/99"
    assert row["pr_number"] == 99
    assert row["sandbox_path"] == ".ai/history/resume-tailor/lts/solution-architect/"
    assert row["feature_branch"] == "feature/lts-solution-architect"
    assert row["started_at"] == "2026-08-30T17:00:00Z"
    assert row["attempt_count"] == 1
    assert row["completed_at"] == "2026-08-30T17:55:00Z"
    assert row["status_updated_at"] == NOW
    assert "failure" not in row
    # Default behavior: deleted if all rows drained
    assert not queue.is_file()
    assert f"Consumed {queue.name}; copied=1 remaining_rows=0" in out


def test_failure_copies_p2e1_object_and_persists_in_queue(repo_layout):
    root = repo_layout["root"]
    platform = repo_layout["platform"]
    write_day(repo_layout["src"], "2026-08-11", [make_job(job_id=JOB_ID)])
    _sidecar(platform)
    _ledger(platform, [_approved_row()])
    failure = {
        "code": "tailor_skill",
        "message": "skill aborted",
        "failed_at": NOW,
        "step": "step-2",
    }
    queue = _queue(
        root,
        [_failed_payload(failure=failure)],
    )
    code, out = _run(root, queue)
    assert code == 0
    row = json.loads((platform / "approved-jobs.json").read_text(encoding="utf-8"))["jobs"][0]
    assert row["status"] == "failed"
    assert row["failure"] == failure
    assert row["started_at"] == "2026-08-30T17:00:00Z"
    assert row["attempt_count"] == 1
    assert row["completed_at"] is None
    # Failed row stays in queue file and queue file persists
    assert queue.is_file()
    queue_data = json.loads(queue.read_text(encoding="utf-8"))
    assert len(queue_data["jobs"]) == 1
    assert queue_data["jobs"][0]["id"] == JOB_ID
    assert queue_data["jobs"][0]["status"] == "failed"
    assert f"Consumed {queue.name}; copied=1 remaining_rows=1" in out


def test_mixed_queue_drains_completed_keeps_failed(repo_layout):
    root = repo_layout["root"]
    platform = repo_layout["platform"]
    job_2 = "greenhouse:lts:200"
    write_day(
        repo_layout["src"],
        "2026-08-11",
        [make_job(job_id=JOB_ID), make_job(job_id=job_2, source_job_id="200")],
    )
    _sidecar(platform, JOB_ID)
    _sidecar(platform, job_2)
    _ledger(platform, [_approved_row(JOB_ID), _approved_row(job_2)])

    queue = _queue(
        root,
        [
            _complete_payload(id=JOB_ID),
            _failed_payload(
                id=job_2,
                company_slug="lts",
                position_slug="solution-architect-200",
            ),
        ],
    )
    code, out = _run(root, queue)
    assert code == 0
    assert queue.is_file()
    queue_data = json.loads(queue.read_text(encoding="utf-8"))
    assert len(queue_data["jobs"]) == 1
    assert queue_data["jobs"][0]["id"] == job_2
    assert queue_data["jobs"][0]["status"] == "failed"

    ledger = json.loads((platform / "approved-jobs.json").read_text(encoding="utf-8"))
    by_id = {row["id"]: row for row in ledger["jobs"]}
    assert by_id[JOB_ID]["status"] == "completed"
    assert by_id[job_2]["status"] == "failed"
    assert f"Consumed {queue.name}; copied=2 remaining_rows=1" in out


def test_collision_missing_ledger_row_fail_closed(repo_layout):
    root = repo_layout["root"]
    platform = repo_layout["platform"]
    write_day(repo_layout["src"], "2026-08-11", [make_job(job_id=JOB_ID)])
    _sidecar(platform)
    _ledger(platform, [])
    queue = _queue(
        root,
        [
            _failed_payload(
                failure={
                    "code": "collision",
                    "message": "sandbox owned by another job_id",
                    "failed_at": NOW,
                    "step": "p2-x1",
                }
            )
        ],
    )
    code, out = _run(root, queue)
    assert code == 1
    assert "ledger row missing" in out


def test_missing_platform_fail_closed(repo_layout):
    root = repo_layout["root"]
    platform = repo_layout["platform"]
    write_day(repo_layout["src"], "2026-08-11", [make_job(job_id=JOB_ID)])
    _sidecar(platform)
    _ledger(platform, [_approved_row()])
    queue = _queue(
        root,
        [_complete_payload()],
        platform=None,
    )
    code, out = _run(root, queue)
    assert code == 1
    assert "platform is required" in out
    row = json.loads((platform / "approved-jobs.json").read_text(encoding="utf-8"))["jobs"][0]
    assert row["status"] == "approved"


def test_bulk_without_queue_file_consumes_all(repo_layout):
    root = repo_layout["root"]
    platform = repo_layout["platform"]
    job_2 = "greenhouse:lts:200"
    write_day(
        repo_layout["src"],
        "2026-08-11",
        [make_job(job_id=JOB_ID), make_job(job_id=job_2, source_job_id="200")],
    )
    _sidecar(platform)
    _sidecar(platform, job_2)
    _ledger(platform, [_approved_row(JOB_ID), _approved_row(job_2)])
    first = _queue(root, [_complete_payload()], run_id="a" * 32, batch_number=2)
    second = _queue(
        root,
        [_complete_payload(id=job_2, pr_number=100, pr_url="https://github.com/example/job-forge/pull/100")],
        run_id="b" * 32,
        batch_number=1,
    )
    code, out = _run(root)
    assert code == 0
    assert not first.is_file()
    assert not second.is_file()
    ledger = json.loads((platform / "approved-jobs.json").read_text(encoding="utf-8"))
    by_id = {row["id"]: row for row in ledger["jobs"]}
    assert by_id[JOB_ID]["status"] == "completed"
    assert by_id[JOB_ID]["pr_number"] == 99
    assert by_id[job_2]["status"] == "completed"
    assert by_id[job_2]["pr_number"] == 100
    assert by_id[job_2]["completed_at"] == "2026-08-30T17:55:00Z"


def test_remaining_row_with_core_themes_still_validates(repo_layout):
    root = repo_layout["root"]
    platform = repo_layout["platform"]
    job_2 = "greenhouse:lts:200"
    write_day(
        repo_layout["src"],
        "2026-08-11",
        [make_job(job_id=JOB_ID), make_job(job_id=job_2, source_job_id="200")],
    )
    _sidecar(platform, JOB_ID)
    _sidecar(platform, job_2)
    _ledger(platform, [_approved_row(JOB_ID), _approved_row(job_2)])
    queue = _queue(
        root,
        [
            _complete_payload(id=JOB_ID),
            _failed_payload(
                id=job_2,
                company_slug="lts",
                position_slug="solution-architect-200",
                core_themes=CORE_THEMES,
            ),
        ],
    )
    code, out = _run(root, queue)
    assert code == 0
    assert queue.is_file()
    assert validate_tailor_request(queue) == []
    queue_data = json.loads(queue.read_text(encoding="utf-8"))
    assert queue_data["jobs"][0]["core_themes"] == CORE_THEMES
    assert f"Consumed {queue.name}; copied=2 remaining_rows=1" in out


def test_bulk_no_files_is_noop(repo_layout):
    root = repo_layout["root"]
    code, out = _run(root)
    assert code == 0
    assert "No tailor queue files" in out
