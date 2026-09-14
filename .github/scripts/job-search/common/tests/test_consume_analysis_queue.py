"""consume_analysis_queue.py G6 pre-handoff consume fixtures."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import common.consume_analysis_queue as consume
from conftest import make_job, write_day

NOW = "2026-08-30T12:00:00Z"
RUN_A = "a" * 32
RUN_B = "b" * 32
PR_URL = "https://github.com/example/job-forge/pull/38"


def _resume_nulls() -> dict:
    return {
        "started_at": None,
        "attempt_count": None,
        "completed_at": None,
        "pr_url": None,
        "pr_number": None,
        "sandbox_path": None,
        "feature_branch": None,
    }


def _first_fill(job_id: str = "greenhouse:lts:100", *, analysis_id: int = 1, **extra) -> dict:
    row = {
        "id": job_id,
        "analysis_id": analysis_id,
        "approved_at": NOW,
        "status": "approved",
        "status_updated_at": NOW,
        **_resume_nulls(),
    }
    row.update(extra)
    return row


def _analysis_row(
    job_id: str,
    *,
    decision: str,
    analysis_id: int,
    is_current: bool,
    skills: list[dict] | None = None,
) -> dict:
    return {
        "analysis_id": analysis_id,
        "job_id": job_id,
        "pull_date": "2026-08-11",
        "revision": 1,
        "is_current": is_current,
        "run_id": RUN_A,
        "analyzed_at": NOW,
        "decision": decision,
        "justification": f"{decision} justification",
        "experience": {"requirements": []},
        "skills": {"requirements": skills or []},
        "constraints": {"requirements": []},
        "external_context": {"decision_impact": "none", "sources": []},
    }


def _sidecar(
    job_id: str,
    *,
    decision: str,
    analysis_id: int = 1,
    skills: list[dict] | None = None,
) -> dict:
    analyses = [
        _analysis_row(job_id, decision=decision, analysis_id=prior, is_current=False)
        for prior in range(1, analysis_id)
    ]
    analyses.append(
        _analysis_row(
            job_id,
            decision=decision,
            analysis_id=analysis_id,
            is_current=True,
            skills=skills,
        )
    )
    return {
        "platform": "greenhouse",
        "job_id": job_id,
        "analysis_id": analysis_id,
        "updated_at": NOW,
        "analyses": analyses,
    }


def _write_sidecar(platform: Path, job_id: str, **kwargs) -> Path:
    encoded = job_id.replace(":", "-")
    analyses = platform / "analyses"
    analyses.mkdir(parents=True, exist_ok=True)
    path = analyses / f"{encoded}-analysis.json"
    path.write_text(json.dumps(_sidecar(job_id, **kwargs)), encoding="utf-8")
    return path


def _write_queue(
    root: Path,
    run_id: str,
    jobs: list[dict],
    *,
    batch: int = 1,
    platform: str | None = "greenhouse",
) -> Path:
    queue_dir = root / ".ai" / "history" / "job-search" / "queue"
    queue_dir.mkdir(parents=True, exist_ok=True)
    path = queue_dir / f"{run_id}-analysis-request.json"
    normalized_jobs = []
    for j in jobs:
        row = {
            "company": "LTS",
            "title": "Solution Architect",
            "location": "New York, NY",
            "work_location_type": "unknown",
            "url": "https://job-boards.greenhouse.io/lts/jobs/100",
            "description_text": "Architect role",
            **j,
        }
        normalized_jobs.append(row)
    payload: dict = {
        "run_id": run_id,
        "batch_number": batch,
        "created_date": "2026-08-21",
        "invoke": "batch",
        "jobs": normalized_jobs,
    }
    if platform is not None:
        payload["platform"] = platform
    path.write_text(
        json.dumps(payload, indent=2)
        + "\n",
        encoding="utf-8",
    )
    return path


def _write_ledger(platform: Path, jobs: list[dict]) -> Path:
    path = platform / "approved-jobs.json"
    path.write_text(
        json.dumps({"platform": "greenhouse", "jobs": jobs}, indent=2)
        + "\n",
        encoding="utf-8",
    )
    return path


def _listing(src: Path, job_id: str = "greenhouse:lts:100") -> None:
    write_day(src, "2026-08-11", [make_job(job_id=job_id)])


def _run(root: Path, queue_file: Path | None = None, extra: list[str] | None = None) -> tuple[int, str]:
    argv = ["--repo-root", str(root)]
    if queue_file is not None:
        argv.extend(["--queue-file", str(queue_file)])
    if extra:
        argv.extend(extra)
    buf = StringIO()
    err = StringIO()
    with patch.object(consume, "utc_now", return_value=NOW):
        old_out, old_err = __import__("sys").stdout, __import__("sys").stderr
        try:
            __import__("sys").stdout = buf
            __import__("sys").stderr = err
            code = consume.main(argv)
        finally:
            __import__("sys").stdout = old_out
            __import__("sys").stderr = old_err
    return code, buf.getvalue() + err.getvalue()


def test_approved_upsert(repo_layout):
    root = repo_layout["root"]
    platform = repo_layout["platform"]
    _listing(repo_layout["src"])
    _write_sidecar(platform, "greenhouse:lts:100", decision="approved")
    queue = _write_queue(root, RUN_A, [{"id": "greenhouse:lts:100", "status": "analysis_complete"}])
    code, _ = _run(root, queue)
    assert code == 0
    assert not queue.is_file()
    ledger = json.loads((platform / "approved-jobs.json").read_text(encoding="utf-8"))
    assert ledger["jobs"] == [_first_fill()]


def test_rejected_deletes_existing_row(repo_layout):
    root = repo_layout["root"]
    platform = repo_layout["platform"]
    _listing(repo_layout["src"])
    _write_sidecar(platform, "greenhouse:lts:100", decision="rejected")
    _write_ledger(
        platform,
        [
            _first_fill(
                approved_at="2026-08-20T12:00:00Z",
                status_updated_at="2026-08-20T12:00:00Z",
            )
        ],
    )
    queue = _write_queue(root, RUN_A, [{"id": "greenhouse:lts:100", "status": "analysis_complete"}])
    code, _ = _run(root, queue)
    assert code == 0
    ledger = json.loads((platform / "approved-jobs.json").read_text(encoding="utf-8"))
    assert ledger["jobs"] == []
    assert not queue.is_file()


def test_rejected_noop_when_row_missing(repo_layout):
    root = repo_layout["root"]
    platform = repo_layout["platform"]
    _listing(repo_layout["src"])
    _write_sidecar(platform, "greenhouse:lts:100", decision="rejected")
    queue = _write_queue(root, RUN_A, [{"id": "greenhouse:lts:100", "status": "analysis_complete"}])
    code, _ = _run(root, queue)
    assert code == 0
    ledger = json.loads((platform / "approved-jobs.json").read_text(encoding="utf-8"))
    assert ledger["jobs"] == []


def test_approved_retargets_existing_row(repo_layout):
    root = repo_layout["root"]
    platform = repo_layout["platform"]
    _listing(repo_layout["src"])
    _write_sidecar(platform, "greenhouse:lts:100", decision="approved", analysis_id=2)
    _write_ledger(
        platform,
        [
            _first_fill(
                analysis_id=1,
                approved_at="2026-08-20T12:00:00Z",
                status_updated_at="2026-08-20T12:00:00Z",
            )
        ],
    )
    queue = _write_queue(root, RUN_A, [{"id": "greenhouse:lts:100", "status": "analysis_complete"}])
    code, _ = _run(root, queue)
    assert code == 0
    ledger = json.loads((platform / "approved-jobs.json").read_text(encoding="utf-8"))
    assert ledger["jobs"][0]["analysis_id"] == 2
    assert ledger["jobs"][0]["approved_at"] == NOW
    assert ledger["jobs"][0]["status_updated_at"] == NOW
    assert ledger["jobs"][0]["status"] == "approved"


def test_partial_prune_keeps_pending(repo_layout):
    root = repo_layout["root"]
    platform = repo_layout["platform"]
    _listing(repo_layout["src"])
    write_day(repo_layout["src"], "2026-08-11", [
        make_job(job_id="greenhouse:lts:100"),
        make_job(job_id="greenhouse:lts:200", source_job_id="200"),
    ])
    _write_sidecar(platform, "greenhouse:lts:100", decision="approved")
    queue = _write_queue(
        root,
        RUN_A,
        [
            {"id": "greenhouse:lts:100", "status": "analysis_complete"},
            {"id": "greenhouse:lts:200", "status": "pending"},
        ],
    )
    code, _ = _run(root, queue)
    assert code == 0
    assert queue.is_file()
    remaining = json.loads(queue.read_text(encoding="utf-8"))
    assert len(remaining["jobs"]) == 1
    assert remaining["jobs"][0]["id"] == "greenhouse:lts:200"
    assert remaining["jobs"][0]["status"] == "pending"
    assert remaining["jobs"][0]["company"] == "LTS"
    assert remaining["jobs"][0]["title"] == "Solution Architect"
    assert remaining["jobs"][0]["location"] == "New York, NY"
    assert remaining["jobs"][0]["work_location_type"] == "unknown"
    assert remaining["jobs"][0]["url"] == "https://job-boards.greenhouse.io/lts/jobs/100"
    assert remaining["jobs"][0]["description_text"] == "Architect role"
    ledger = json.loads((platform / "approved-jobs.json").read_text(encoding="utf-8"))
    assert [row["id"] for row in ledger["jobs"]] == ["greenhouse:lts:100"]


def test_empty_file_deleted(repo_layout):
    root = repo_layout["root"]
    platform = repo_layout["platform"]
    _listing(repo_layout["src"])
    _write_sidecar(platform, "greenhouse:lts:100", decision="rejected")
    queue = _write_queue(root, RUN_A, [{"id": "greenhouse:lts:100", "status": "analysis_complete"}])
    code, _ = _run(root, queue)
    assert code == 0
    assert not queue.is_file()


def test_validate_fail_closed_missing_jobs_json(repo_layout):
    root = repo_layout["root"]
    platform = repo_layout["platform"]
    _write_sidecar(platform, "greenhouse:lts:100", decision="approved")
    queue = _write_queue(root, RUN_A, [{"id": "greenhouse:lts:100", "status": "analysis_complete"}])
    code, out = _run(root, queue)
    assert code == 1
    assert "ledger validator failed" in out


def test_auto_selects_lowest_batch_with_analysis_complete(repo_layout):
    root = repo_layout["root"]
    platform = repo_layout["platform"]
    _listing(repo_layout["src"])
    write_day(
        repo_layout["src"],
        "2026-08-11",
        [
            make_job(job_id="greenhouse:lts:100"),
            make_job(job_id="greenhouse:lts:200", source_job_id="200"),
        ],
    )
    _write_sidecar(platform, "greenhouse:lts:100", decision="approved")
    _write_sidecar(platform, "greenhouse:lts:200", decision="approved")
    pending_only = _write_queue(
        root, RUN_B, [{"id": "greenhouse:lts:200", "status": "pending"}], batch=1
    )
    complete = _write_queue(
        root, RUN_A, [{"id": "greenhouse:lts:100", "status": "analysis_complete"}], batch=2
    )
    code, _ = _run(root)
    assert code == 0
    assert pending_only.is_file()
    assert not complete.is_file()


def test_post_handoff_deployed_not_deleted_on_reject(repo_layout):
    root = repo_layout["root"]
    platform = repo_layout["platform"]
    _listing(repo_layout["src"])
    _write_sidecar(platform, "greenhouse:lts:100", decision="rejected")
    _write_ledger(
        platform,
        [
            _first_fill(
                status="deployed",
                sandbox_path=".ai/history/resume-tailor/lts/solution-architect/",
                artifacts_url="https://drive.google.com/drive/folders/abc123",
            )
        ],
    )
    queue = _write_queue(root, RUN_A, [{"id": "greenhouse:lts:100", "status": "analysis_complete"}])
    code, _ = _run(root, queue)
    assert code == 0
    ledger = json.loads((platform / "approved-jobs.json").read_text(encoding="utf-8"))
    assert ledger["jobs"][0]["status"] == "deployed"
    assert ledger["jobs"][0]["artifacts_url"] == "https://drive.google.com/drive/folders/abc123"


def test_post_handoff_completed_retargeted_without_job_id(repo_layout):
    root = repo_layout["root"]
    platform = repo_layout["platform"]
    _listing(repo_layout["src"])
    _write_sidecar(platform, "greenhouse:lts:100", decision="approved", analysis_id=3)
    _write_ledger(
        platform,
        [
            _first_fill(
                analysis_id=1,
                approved_at="2026-08-20T12:00:00Z",
                status="completed",
                completed_at=NOW,
                pr_number=38,
                pr_url=PR_URL,
                sandbox_path=".ai/history/resume-tailor/lts/solution-architect/",
                feature_branch="feature/lts-solution-architect",
                started_at=NOW,
                attempt_count=1,
            )
        ],
    )
    queue = _write_queue(root, RUN_A, [{"id": "greenhouse:lts:100", "status": "analysis_complete"}])
    code, _ = _run(root, queue)
    assert code == 0
    ledger = json.loads((platform / "approved-jobs.json").read_text(encoding="utf-8"))
    row = ledger["jobs"][0]
    assert row["analysis_id"] == 3
    assert row["status"] == "approved"
    assert row["approved_at"] == NOW
    assert row["status_updated_at"] == NOW
    assert row["pr_number"] == 38
    assert row["pr_url"] == PR_URL
    assert row["sandbox_path"] == ".ai/history/resume-tailor/lts/solution-architect/"
    assert row["feature_branch"] == "feature/lts-solution-architect"
    assert row["started_at"] == NOW
    assert row["attempt_count"] == 1
    assert row["completed_at"] == NOW


def test_job_id_overwrites_completed_row(repo_layout):
    root = repo_layout["root"]
    platform = repo_layout["platform"]
    _listing(repo_layout["src"])
    _write_sidecar(platform, "greenhouse:lts:100", decision="approved", analysis_id=3)
    _write_ledger(
        platform,
        [
            _first_fill(
                analysis_id=1,
                approved_at="2026-08-20T12:00:00Z",
                status="completed",
                started_at=NOW,
                attempt_count=1,
                completed_at=NOW,
                pr_number=38,
                pr_url=PR_URL,
                sandbox_path=".ai/history/resume-tailor/lts/solution-architect/",
                feature_branch="feature/lts-solution-architect",
            )
        ],
    )
    queue = _write_queue(root, RUN_A, [{"id": "greenhouse:lts:100", "status": "analysis_complete"}])
    code, _ = _run(root, queue, ["--job-id", "greenhouse:lts:100"])
    assert code == 0
    ledger = json.loads((platform / "approved-jobs.json").read_text(encoding="utf-8"))
    assert ledger["jobs"] == [
        _first_fill(
            analysis_id=3,
            started_at=NOW,
            attempt_count=1,
            completed_at=NOW,
            pr_number=38,
            pr_url=PR_URL,
            sandbox_path=".ai/history/resume-tailor/lts/solution-architect/",
            feature_branch="feature/lts-solution-architect",
        )
    ]


def test_analysis_complete_rows_all_retarget_including_siblings(repo_layout):
    root = repo_layout["root"]
    platform = repo_layout["platform"]
    write_day(
        repo_layout["src"],
        "2026-08-11",
        [
            make_job(job_id="greenhouse:lts:100"),
            make_job(job_id="greenhouse:lts:200", source_job_id="200"),
        ],
    )
    _write_sidecar(platform, "greenhouse:lts:100", decision="approved", analysis_id=3)
    _write_sidecar(platform, "greenhouse:lts:200", decision="approved", analysis_id=2)
    _write_ledger(
        platform,
        [
            _first_fill(
                status="completed",
                approved_at="2026-08-20T12:00:00Z",
                completed_at=NOW,
                pr_number=38,
                pr_url=PR_URL,
            ),
            _first_fill(
                job_id="greenhouse:lts:200",
                status="completed",
                approved_at="2026-08-20T12:00:00Z",
                completed_at=NOW,
                pr_number=39,
                pr_url="https://github.com/example/job-forge/pull/39",
            ),
        ],
    )
    queue = _write_queue(
        root,
        RUN_A,
        [
            {"id": "greenhouse:lts:100", "status": "analysis_complete"},
            {"id": "greenhouse:lts:200", "status": "analysis_complete"},
        ],
    )
    code, _ = _run(root, queue, ["--job-id", "greenhouse:lts:100"])
    assert code == 0
    ledger = json.loads((platform / "approved-jobs.json").read_text(encoding="utf-8"))
    by_id = {row["id"]: row for row in ledger["jobs"]}
    assert by_id["greenhouse:lts:100"]["analysis_id"] == 3
    assert by_id["greenhouse:lts:100"]["status"] == "approved"
    assert by_id["greenhouse:lts:100"]["pr_number"] == 38
    assert by_id["greenhouse:lts:200"]["analysis_id"] == 2
    assert by_id["greenhouse:lts:200"]["status"] == "approved"
    assert by_id["greenhouse:lts:200"]["pr_number"] == 39


def test_job_id_reject_deletes_completed_row(repo_layout):
    root = repo_layout["root"]
    platform = repo_layout["platform"]
    _listing(repo_layout["src"])
    _write_sidecar(platform, "greenhouse:lts:100", decision="rejected", analysis_id=3)
    _write_ledger(
        platform,
        [
            _first_fill(
                status="completed",
                pr_number=38,
                pr_url=PR_URL,
                completed_at=NOW,
            )
        ],
    )
    queue = _write_queue(root, RUN_A, [{"id": "greenhouse:lts:100", "status": "analysis_complete"}])
    code, _ = _run(root, queue, ["--job-id", "greenhouse:lts:100"])
    assert code == 0
    ledger = json.loads((platform / "approved-jobs.json").read_text(encoding="utf-8"))
    assert ledger["jobs"] == []


def test_job_id_empty_fail_closed(repo_layout):
    root = repo_layout["root"]
    code, out = _run(root, extra=["--job-id", "  ,  "])
    assert code == 1
    assert "--job-id requires at least one id" in out


def test_job_id_without_queue_overwrites_completed_from_sidecar(repo_layout):
    root = repo_layout["root"]
    platform = repo_layout["platform"]
    _listing(repo_layout["src"])
    _write_sidecar(platform, "greenhouse:lts:100", decision="approved", analysis_id=4)
    _write_ledger(
        platform,
        [
            _first_fill(
                analysis_id=1,
                approved_at="2026-08-20T12:00:00Z",
                status="completed",
                pr_number=38,
                pr_url=PR_URL,
                completed_at=NOW,
            )
        ],
    )
    leftover = _write_queue(
        root, RUN_B, [{"id": "greenhouse:lts:200", "status": "analysis_complete"}]
    )
    code, out = _run(root, extra=["--job-id", "greenhouse:lts:100"])
    assert code == 0
    assert leftover.is_file()
    assert "Retargeted greenhouse/approved-jobs.json" in out
    ledger = json.loads((platform / "approved-jobs.json").read_text(encoding="utf-8"))
    assert ledger["jobs"] == [
        _first_fill(
            analysis_id=4,
            pr_number=38,
            pr_url=PR_URL,
            completed_at=NOW,
        )
    ]


def test_job_id_without_queue_missing_sidecar_fail_closed(repo_layout):
    root = repo_layout["root"]
    _listing(repo_layout["src"])
    code, out = _run(root, extra=["--job-id", "greenhouse:lts:100"])
    assert code == 1
    assert "sidecar missing" in out


def test_missing_platform_fail_closed(repo_layout):
    root = repo_layout["root"]
    platform = repo_layout["platform"]
    queue = _write_queue(
        root,
        RUN_A,
        [{"id": "greenhouse:lts:100", "status": "analysis_complete"}],
        platform=None,
    )
    code, out = _run(root, queue)
    assert code == 1
    assert "platform is required" in out
    assert not (platform / "approved-jobs.json").is_file()


def test_empty_platform_fail_closed(repo_layout):
    root = repo_layout["root"]
    queue = _write_queue(
        root,
        RUN_A,
        [{"id": "greenhouse:lts:100", "status": "analysis_complete"}],
        platform="",
    )
    code, out = _run(root, queue)
    assert code == 1
    assert "platform is required" in out
