"""Map Greenhouse Job Board API payloads to the locked job-search data model."""

from __future__ import annotations

import html
import re
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
import sys

_JOB_SEARCH = Path(__file__).resolve().parents[1]
if str(_JOB_SEARCH) not in sys.path:
    sys.path.insert(0, str(_JOB_SEARCH))

from common.clock import now_iso

# Allowlisted Greenhouse metadata field names (case-insensitive).
# Recognized values take precedence over location.name / offices[].name.
_METADATA_FIELD_ALLOWLIST = frozenset(
    {
        "workplace type",
        "work location type",
        "work arrangement",
        "location type",
        "remote",
        "remote status",
        "employment location type",
    }
)

_REMOTE_TOKENS = ("remote",)
_HYBRID_TOKENS = ("hybrid",)
_ONSITE_TOKENS = ("onsite", "on-site", "on site")


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text:
            self._parts.append(text)

    def get_text(self) -> str:
        return " ".join(self._parts)


def html_to_text(value: str | None) -> str:
    if not value:
        return ""
    parser = _HTMLTextExtractor()
    try:
        parser.feed(html.unescape(value))
        return re.sub(r"\s+", " ", parser.get_text()).strip()
    except Exception:
        cleaned = re.sub(r"<[^>]+>", " ", html.unescape(value))
        return re.sub(r"\s+", " ", cleaned).strip()


def _office_location(job: dict[str, Any]) -> str:
    offices = job.get("offices") or []
    names: list[str] = []
    for office in offices:
        name = (office or {}).get("name")
        if name:
            names.append(str(name))
    location = job.get("location") or {}
    loc_name = location.get("name") if isinstance(location, dict) else None
    if loc_name and loc_name not in names:
        names.insert(0, str(loc_name))
    return ", ".join(names)


def _token_to_work_location_type(blob: str) -> str | None:
    """Return remote|hybrid|onsite if an arrangement token is present, else None."""
    lower = blob.lower()
    if any(tok in lower for tok in _REMOTE_TOKENS):
        return "remote"
    if any(tok in lower for tok in _HYBRID_TOKENS):
        return "hybrid"
    if any(tok in lower for tok in _ONSITE_TOKENS):
        return "onsite"
    return None


def _metadata_entries(metadata: Any) -> list[tuple[str, str]]:
    """Normalize Greenhouse metadata into (name, value) pairs."""
    entries: list[tuple[str, str]] = []
    if not metadata:
        return entries
    if isinstance(metadata, dict):
        for key, value in metadata.items():
            if value is None:
                continue
            entries.append((str(key), str(value)))
        return entries
    if isinstance(metadata, list):
        for item in metadata:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("key") or ""
            value = item.get("value")
            if value is None:
                continue
            if isinstance(value, list):
                value = " ".join(str(v) for v in value if v is not None)
            entries.append((str(name), str(value)))
    return entries


def extract_work_location_type(
    location_name: str | None,
    offices: list[dict[str, Any]] | None,
    metadata: Any = None,
) -> str:
    """Derive work_location_type with metadata allowlist precedence, then location fields.

    description_text is never scanned — arrangement tokens there produce false positives.
    Bare geography (non-empty location/office names without arrangement tokens) yields unknown.
    """
    for name, value in _metadata_entries(metadata):
        if name.strip().lower() not in _METADATA_FIELD_ALLOWLIST:
            continue
        mapped = _token_to_work_location_type(value)
        if mapped is not None:
            return mapped
        # Unrecognized allowlisted metadata value: fall through to location parsing.

    parts: list[str] = []
    if location_name and str(location_name).strip():
        parts.append(str(location_name).strip())
    for office in offices or []:
        name = (office or {}).get("name")
        if name and str(name).strip():
            parts.append(str(name).strip())

    blob = " ".join(parts)
    if not blob.strip():
        return "unknown"

    mapped = _token_to_work_location_type(blob)
    if mapped is not None:
        return mapped
    return "unknown"


def build_job_id(board_token: str, source_job_id: str) -> str:
    return f"greenhouse:{board_token}:{source_job_id}"


def parse_posted_at(value: Any, pull_date: str) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None

    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text

    slash = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if slash:
        month, day, year = int(slash.group(1)), int(slash.group(2)), int(slash.group(3))
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            return None

    unpadded = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if unpadded:
        year, month, day = int(unpadded.group(1)), int(unpadded.group(2)), int(unpadded.group(3))
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            return None

    normalized = text
    if normalized.endswith(" UTC"):
        normalized = normalized[:-4] + "+00:00"
    elif normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(normalized).astimezone(timezone.utc).date().isoformat()
    except ValueError:
        pass

    try:
        base = date.fromisoformat(pull_date)
    except ValueError:
        return None

    lower = text.lower()
    if lower in {"today", "just posted", "just now"}:
        return base.isoformat()
    if lower == "yesterday":
        return (base - timedelta(days=1)).isoformat()
    if re.fullmatch(r"\d+\+?\s+(hour|hours|minute|minutes)\s+ago", lower):
        return base.isoformat()
    match = re.fullmatch(r"(\d+)\+?\s+days?\s+ago", lower)
    if match:
        return (base - timedelta(days=int(match.group(1)))).isoformat()
    return None


def normalize_greenhouse_job(
    job: dict[str, Any],
    *,
    board_token: str,
    company: str,
    pull_date: str,
    status_updated_at: str,
    prior_jobs: dict[str, dict[str, Any]] | None = None,
    prior_ids: set[str] | None = None,
    include_raw: bool = False,
    force_status: str | None = None,
) -> dict[str, Any]:
    source_job_id = str(job.get("id", "")).strip()
    if not source_job_id:
        raise ValueError("Greenhouse job missing id")

    job_id = build_job_id(board_token, source_job_id)
    title = str(job.get("title") or "").strip()
    location = _office_location(job)
    absolute_url = str(job.get("absolute_url") or "").strip()
    description_text = html_to_text(job.get("content"))

    loc_obj = job.get("location") or {}
    location_name = loc_obj.get("name") if isinstance(loc_obj, dict) else None
    offices = job.get("offices") if isinstance(job.get("offices"), list) else []
    work_location_type = extract_work_location_type(
        location_name,
        offices,
        job.get("metadata"),
    )

    prior_index = prior_jobs if prior_jobs is not None else {i: {} for i in (prior_ids or set())}
    if force_status is not None:
        status = force_status
        presence_ts = status_updated_at
    elif job_id in prior_index:
        status = "active"
        prior_row = prior_index[job_id]
        if str(prior_row.get("status") or "") == "active" and prior_row.get("status_updated_at"):
            presence_ts = str(prior_row["status_updated_at"])
        else:
            presence_ts = status_updated_at
    else:
        status = "new"
        presence_ts = status_updated_at

    posted_at = parse_posted_at(job.get("first_published") or job.get("created_at"), pull_date)
    if posted_at is None and job_id in prior_index:
        prior_posted_at = prior_index[job_id].get("posted_at")
        if isinstance(prior_posted_at, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", prior_posted_at):
            posted_at = prior_posted_at

    record: dict[str, Any] = {
        "id": job_id,
        "source_job_id": source_job_id,
        "status": status,
        "title": title,
        "company": company,
        "location": location,
        "work_location_type": work_location_type,
        "url": absolute_url,
        "pulled_at": pull_date,
        "posted_at": posted_at,
        "status_updated_at": presence_ts,
        "description_text": description_text,
    }
    if include_raw:
        record["raw"] = {
            "id": job.get("id"),
            "updated_at": job.get("updated_at"),
            "requisition_id": job.get("requisition_id"),
        }
    return record


__all__ = [
    "extract_work_location_type",
    "html_to_text",
    "normalize_greenhouse_job",
    "now_iso",
    "parse_posted_at",
]
