"""Validate a 1b analysis-request queue file after generate-analysis-queue.py writes it."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RUN_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_STATUS = {"pending", "analysis_complete"}
_INVOKE = {"manual", "batch"}
_WORK_LOCATION_TYPES = {"remote", "hybrid", "onsite", "unknown"}
_REQUIRED_STRINGS = ("company", "title", "location", "url", "description_text")
_ALLOWED_JOB_KEYS = frozenset(
    {"id", "status", "skip_reason", "company", "title", "location", "work_location_type", "url", "description_text"}
)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_analysis_request(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        doc = load_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        return [f"cannot read queue file: {exc}"]
    if not isinstance(doc, dict):
        return ["queue file root must be an object"]

    run_id = str(doc.get("run_id") or "")
    stem = path.name[: -len("-analysis-request.json")] if path.name.endswith("-analysis-request.json") else ""
    if not _RUN_ID_RE.fullmatch(run_id):
        errors.append(f"run_id: must be 32-char lowercase hex, got {run_id!r}")
    if stem and stem != run_id:
        errors.append(f"run_id: envelope {run_id!r} must equal filename stem {stem!r}")
    if "schema_version" in doc:
        errors.append("envelope must not include schema_version")
    if "mode" in doc:
        errors.append("envelope must not include mode")
    if "pull_date" in doc:
        errors.append("envelope must not include pull_date")
    invoke = doc.get("invoke")
    if invoke not in _INVOKE:
        errors.append("invoke: required enum manual|batch")
    batch = doc.get("batch_number")
    if not isinstance(batch, int) or batch < 1:
        errors.append("batch_number: must be integer >= 1")
    created = str(doc.get("created_date") or "")
    if not _DATE_RE.fullmatch(created):
        errors.append("created_date: must be YYYY-MM-DD")
    if not str(doc.get("platform") or "").strip():
        errors.append("platform: required")

    jobs = doc.get("jobs")
    if not isinstance(jobs, list) or not jobs:
        errors.append("jobs: must be a non-empty array")
        return errors
    seen: set[str] = set()
    for index, row in enumerate(jobs):
        if not isinstance(row, dict):
            errors.append(f"jobs[{index}]: must be an object")
            continue
        if "mode" in row:
            errors.append(f"jobs[{index}]: must not include mode")
        job_id = str(row.get("id") or "")
        if not job_id:
            errors.append(f"jobs[{index}].id: required")
        elif job_id in seen:
            errors.append(f"jobs[{index}].id: duplicate {job_id!r}")
        else:
            seen.add(job_id)
        status = row.get("status")
        if status not in _STATUS:
            errors.append(f"jobs[{index}].status: must be pending or analysis_complete")
        extra = set(row.keys()) - _ALLOWED_JOB_KEYS
        if extra:
            errors.append(f"jobs[{index}]: unexpected keys {sorted(extra)}")
        for key in _REQUIRED_STRINGS:
            val = row.get(key)
            if not isinstance(val, str) or not val.strip():
                errors.append(f"jobs[{index}].{key}: required non-empty string")
        wlt = row.get("work_location_type")
        if wlt not in _WORK_LOCATION_TYPES:
            errors.append(f"jobs[{index}].work_location_type: required enum remote|hybrid|onsite|unknown")
        if "skip_reason" in row:
            if not isinstance(row.get("skip_reason"), str):
                errors.append(f"jobs[{index}].skip_reason: must be a string")
            elif status == "analysis_complete":
                errors.append(f"jobs[{index}].skip_reason: must be cleared when status is analysis_complete")
    return errors
