"""Load a policy record from locked-agent-policies.json by id."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_JOB_SEARCH = Path(__file__).resolve().parents[1]
if str(_JOB_SEARCH) not in sys.path:
    sys.path.insert(0, str(_JOB_SEARCH))

from common.validate_job_search import load_json

POLICY_FILENAME = "locked-agent-policies.json"
JOB_ANALYSIS_POLICY_ID = "job_analysis_policy_001"
RESUME_TAILOR_POLICY_ID = "resume_tailor_policy_001"


def load_agent_policy(root: Path, policy_id: str) -> dict[str, Any]:
    path = root / ".ai" / "guardrails" / POLICY_FILENAME
    doc = load_json(path)
    for rec in doc.get("policies") or []:
        if isinstance(rec, dict) and rec.get("id") == policy_id:
            return rec
    raise KeyError(f"policy {policy_id!r} not found in {path}")
