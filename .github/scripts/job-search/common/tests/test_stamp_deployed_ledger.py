"""stamp_deployed_ledger.py empty-mapping no-op and sandbox join."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from conftest import make_job, write_day

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))
from test_approved_job_schema import JOB_ID, NOW, _sidecar  # noqa: E402

CI_DIR = Path(__file__).resolve().parents[5] / "scripts" / "ci"
sys.path.insert(0, str(CI_DIR))

import stamp_deployed_ledger as stamp  # noqa: E402

SANDBOX = ".ai/history/resume-tailor/lts/servicenow-qa-analyst/"
URL = "https://drive.google.com/drive/folders/abc123"


def _completed_row() -> dict:
    return {
        "id": JOB_ID,
        "analysis_id": 1,
        "approved_at": NOW,
        "status": "completed",
        "status_updated_at": NOW,
        "started_at": NOW,
        "attempt_count": 1,
        "completed_at": NOW,
        "pr_number": 20,
        "pr_url": "https://github.com/example/job-forge/pull/20",
        "sandbox_path": SANDBOX,
        "feature_branch": "feature/lts-servicenow-qa-analyst",
    }


def test_empty_mapping_does_not_stamp(repo_layout):
    root = repo_layout["root"]
    platform = repo_layout["platform"]
    write_day(repo_layout["src"], "2026-08-11", [make_job(job_id=JOB_ID)])
    _sidecar(platform)
    path = platform / "approved-jobs.json"
    path.write_text(
        json.dumps({"platform": "greenhouse", "jobs": [_completed_row()]}, indent=2) + "\n",
        encoding="utf-8",
    )
    assert stamp.apply_folders(root, [], NOW) == 0
    row = json.loads(path.read_text(encoding="utf-8"))["jobs"][0]
    assert row["status"] == "completed"
    assert "artifacts_url" not in row


def test_stamps_completed_on_sandbox_join(repo_layout):
    root = repo_layout["root"]
    platform = repo_layout["platform"]
    write_day(repo_layout["src"], "2026-08-11", [make_job(job_id=JOB_ID)])
    _sidecar(platform)
    path = platform / "approved-jobs.json"
    path.write_text(
        json.dumps({"platform": "greenhouse", "jobs": [_completed_row()]}, indent=2) + "\n",
        encoding="utf-8",
    )
    folders = [
        {
            "resume_tailor_directory": SANDBOX.rstrip("/"),
            "artifacts_url": URL,
        }
    ]
    assert stamp.apply_folders(root, folders, NOW) == 0
    row = json.loads(path.read_text(encoding="utf-8"))["jobs"][0]
    assert row["status"] == "deployed"
    assert row["artifacts_url"] == URL
