"""Validate a resume-tailor queue file after generate-tailor-queue.py writes it."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RUN_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_STATUS = {"pending", "tailor_complete", "failed"}
_RESUME_KEYS = {
    "started_at",
    "attempt_count",
    "completed_at",
    "pr_url",
    "pr_number",
    "sandbox_path",
    "feature_branch",
}
_CORE_THEME_KEYS = (
    "job_skill_1",
    "job_skill_2",
    "job_skill_3",
    "strength_1",
    "strength_2",
    "strength_3",
    "opening_hook",
)
_MINT_KEYS = {
    "id",
    "status",
    "company",
    "title",
    "company_slug",
    "position_slug",
    "location",
    "url",
    "description_text",
    "decision",
    "justification",
    "unmet_mandatory",
    "mentioned_skills",
    "core_themes",
} | _RESUME_KEYS
_COMPLETE_KEYS = _MINT_KEYS
_FAILED_KEYS = _MINT_KEYS | {"failure"}
_COMPLETE_REQUIRED = (
    "pr_url",
    "pr_number",
    "sandbox_path",
    "feature_branch",
    "started_at",
    "completed_at",
    "attempt_count",
)
_FAILURE_CODES = {
    "collision",
    "tailor_preflight",
    "tailor_skill",
    "validate",
    "git",
    "pr_create",
    "unknown",
}
_REQUIREMENT_KEYS = {
    "jd_excerpt",
    "normalized",
    "source_section",
    "importance",
    "result",
    "evidence",
    "note",
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _check_requirement(item: Any, prefix: str) -> list[str]:
    if not isinstance(item, dict):
        return [f"{prefix}: must be an object"]
    extra = set(item.keys()) - _REQUIREMENT_KEYS
    errors = [f"{prefix}: unexpected keys {sorted(extra)}"] if extra else []
    missing = _REQUIREMENT_KEYS - set(item.keys())
    if missing:
        errors.append(f"{prefix}: missing keys {sorted(missing)}")
    return errors


def validate_tailor_request(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        doc = load_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        return [f"cannot read queue file: {exc}"]
    if not isinstance(doc, dict):
        return ["queue file root must be an object"]

    run_id = str(doc.get("run_id") or "")
    stem = path.name[: -len("-tailor-request.json")] if path.name.endswith("-tailor-request.json") else ""
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
        prefix = f"jobs[{index}]"
        if not isinstance(row, dict):
            errors.append(f"{prefix}: must be an object")
            continue
        if "mode" in row:
            errors.append(f"{prefix}: must not include mode")
        job_id = str(row.get("id") or "")
        if not job_id:
            errors.append(f"{prefix}.id: required")
        elif job_id in seen:
            errors.append(f"{prefix}.id: duplicate {job_id!r}")
        else:
            seen.add(job_id)
        status = row.get("status")
        if status not in _STATUS:
            errors.append(f"{prefix}.status: must be pending, tailor_complete, or failed")
        allowed = _MINT_KEYS
        if status == "tailor_complete":
            allowed = _COMPLETE_KEYS
            for key in _COMPLETE_REQUIRED:
                if key not in row or row.get(key) is None:
                    errors.append(f"{prefix}.{key}: required when status is tailor_complete")
            if "pr_number" in row and row.get("pr_number") is not None and not isinstance(row.get("pr_number"), int):
                errors.append(f"{prefix}.pr_number: must be an integer")
            if "attempt_count" in row and row.get("attempt_count") is not None and (
                not isinstance(row.get("attempt_count"), int) or int(row.get("attempt_count")) < 0
            ):
                errors.append(f"{prefix}.attempt_count: must be an integer >= 0")
        elif status == "failed":
            allowed = _FAILED_KEYS
            failure = row.get("failure")
            if not isinstance(failure, dict):
                errors.append(f"{prefix}.failure: required object when status is failed")
            else:
                for key in ("code", "message", "failed_at", "step"):
                    if key not in failure:
                        errors.append(f"{prefix}.failure.{key}: required")
                if failure.get("code") not in _FAILURE_CODES:
                    errors.append(f"{prefix}.failure.code: invalid")
                failed_at = str(failure.get("failed_at") or "")
                try:
                    datetime.strptime(failed_at.replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S%z")
                except ValueError:
                    errors.append(f"{prefix}.failure.failed_at: must be UTC Z")
        if status in {"pending", "failed"}:
            if "pr_number" in row and row.get("pr_number") is not None and not isinstance(row.get("pr_number"), int):
                errors.append(f"{prefix}.pr_number: must be an integer")
            if "attempt_count" in row and row.get("attempt_count") is not None and (
                not isinstance(row.get("attempt_count"), int) or int(row.get("attempt_count")) < 0
            ):
                errors.append(f"{prefix}.attempt_count: must be an integer >= 0")
        for ts_key in ("started_at", "completed_at"):
            value = row.get(ts_key) if ts_key in row else None
            if value is not None:
                try:
                    datetime.strptime(str(value).replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S%z")
                except ValueError:
                    errors.append(f"{prefix}.{ts_key}: must be UTC Z")
        extra = set(row.keys()) - allowed
        if extra:
            errors.append(f"{prefix}: unexpected keys {sorted(extra)}")
        for key in (
            "company",
            "title",
            "company_slug",
            "position_slug",
            "location",
            "url",
            "description_text",
            "decision",
            "justification",
        ):
            if key not in row:
                errors.append(f"{prefix}.{key}: required")
        for slug_key in ("company_slug", "position_slug"):
            slug = str(row.get(slug_key) or "")
            if slug and not _SLUG_RE.fullmatch(slug):
                errors.append(f"{prefix}.{slug_key}: must be kebab-case, got {slug!r}")
        unmet = row.get("unmet_mandatory")
        if not isinstance(unmet, list):
            errors.append(f"{prefix}.unmet_mandatory: must be an array")
        else:
            for uidx, item in enumerate(unmet):
                if not isinstance(item, dict) or "normalized" not in item or "note" not in item:
                    errors.append(f"{prefix}.unmet_mandatory[{uidx}]: must have normalized and note")
        mentioned = row.get("mentioned_skills")
        if not isinstance(mentioned, list):
            errors.append(f"{prefix}.mentioned_skills: must be an array")
        else:
            for sidx, item in enumerate(mentioned):
                errors.extend(_check_requirement(item, f"{prefix}.mentioned_skills[{sidx}]"))
        if "core_themes" in row:
            errors.extend(_check_core_themes(row.get("core_themes"), prefix))
    return errors


def _check_core_themes(value: Any, prefix: str) -> list[str]:
    if not isinstance(value, dict):
        return [f"{prefix}.core_themes: must be an object"]
    errors: list[str] = []
    extra = set(value.keys()) - set(_CORE_THEME_KEYS)
    if extra:
        errors.append(f"{prefix}.core_themes: unexpected keys {sorted(extra)}")
    missing = [key for key in _CORE_THEME_KEYS if key not in value]
    if missing:
        errors.append(f"{prefix}.core_themes: missing keys {missing}")
    for key in _CORE_THEME_KEYS:
        if key not in value:
            continue
        item = value.get(key)
        if not isinstance(item, str) or not item.strip():
            errors.append(f"{prefix}.core_themes.{key}: must be a non-empty string")
    return errors
