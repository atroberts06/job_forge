"""Normalize SerpApi Google Jobs payloads to the locked job-search model."""

from __future__ import annotations

import hashlib
import importlib.util
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve()
_JOB_SEARCH = _HERE.parents[1]
_REPO_ROOT = _HERE.parents[4]
if str(_JOB_SEARCH) not in sys.path:
    sys.path.insert(0, str(_JOB_SEARCH))

from greenhouse.normalize import extract_work_location_type

try:
    from greenhouse.normalize import parse_posted_at as _shared_parse_posted_at
except ImportError:  # pragma: no cover - exercised only before ADR-039 lands.
    _shared_parse_posted_at = None


def _load_ci_kebab_case():
    ci_common = _REPO_ROOT / "scripts" / "ci" / "common.py"
    spec = importlib.util.spec_from_file_location("ci_common", ci_common)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load CI common helpers from {ci_common}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.kebab_case


kebab_case = _load_ci_kebab_case()

DATE_POSTED_CATALOG: dict[str, dict[str, str]] = {
    "yesterday": {
        "name": "Yesterday",
        "q_suffix": "since yesterday",
        "uds": "AOm0WdE2fekQnsyfYEw8JPYozOKz9SBxEHkNPSntibKbrgy1zCuDO0hn-m4f-wVx1X6VGgd1aNAUszf-cnj9l-ouz4yYopHvTvY31qVlFKXfw14Cq-QY9zoP0r9tICzOpFRlRTONroWUq4Vg7uhbn2pYkxzNq2e5oBd--O2PndFRBxKRH-ZNfD-zgmrzpOvOrc8SPwb0oEhUN1QUThBrkKtE_uEDcXCnjA6yUJZsOWb2JBHT0959qNTEt4N6Gqzes97EG-tChg7MJQLDc5jo91BRyfdMAC6ETG-p3W73LtQJ9XjqbqwoOzfBxhCKj0hKReFOOcfUh-Nfc1Sx8w90knbTxPNksp9Bbw",
    },
    "last_3_days": {
        "name": "Last 3 days",
        "q_suffix": "in the last 3 days",
        "uds": "AOm0WdE2fekQnsyfYEw8JPYozOKz9gQYSoNMFjnsJA1yb9yQwtTH1lT-WDsg7ihaqMnstRJf5ieT3lajyMnR-bi0zNc11_hZiXpoRfsNXZA8tuae6tAnhcw-zvLhuwXl3o1NPYE2r2mhNxPwG41FA5vGjSUC1pzyGa4OSE0VIOArzrDSn9slKKFjuIn3FN1dkyZVMm5WDpzURhUp2P6lF2b7179uu5dUvdHKHYFc-X6LmpAqH9dGRYb7aVDTUG5KXPtZSSihA5t6p5iwojHxM1qE_S-GD521Gf4QcDhkYAZFb2w-r0AFObfGMHSs3dgZFdw-EFah-zlQ6aO_Gq8kQsFz60ADJohtKQ",
    },
    "last_week": {
        "name": "Last week",
        "q_suffix": "in the last week",
        "uds": "AOm0WdE2fekQnsyfYEw8JPYozOKz8PpUjbL7h6UHeKROf-yJM_ND2fGPUtRa61s40szmYdYdPqErt6g4L_Zx42kz-F82V467l-LLQTipsS-A9TQDeS-UcaM7GgBKtO7t0429_27Xi3wYBeOaB-cQv_61KNOePyZ_fgY07ZrNlogHWCRjlnRzcFmk7sJWqjM5t4SeOaI9z-dJUHNFKUyVAoBu7SWB_JSiArvovMK6R4MWr9V8IWTKU5kla-7xJaJs77cGpZfTQ5EwAEvt9HuI38h9vUhmrO9uhqv3cpjKfFzrMi974kUR3v9kOVSxN2QAE4_8qXOZCc-kVvj68iDSiekgPBCrMOhNRg",
    },
    "last_month": {
        "name": "Last month",
        "q_suffix": "in the last month",
        "uds": "AOm0WdE2fekQnsyfYEw8JPYozOKzlYyFZPNZ4ZWiRigQ-nFMCCtvYtXj7wSoJ-P6kYVkOOPy7BnINjvWA8Sz2mW8A_37d5phBDPz-bE9oR-2fP5lcGdknfyDd7jogPiisHUc5qbpLs9BRdfclCNr3ivZIKPHoaFo6dxDZDZcDNs-UsUJLcbyF8oRNM7JjL4HV_RjHpj042sa9ADzGNUKyTs8VLlOF3xFaFktAVQN8PnheyhXYEPnDqWxnumHZrGjKy2RXPbz1kwwHafMiZHPMjm_RmdKHh-HpflItGHzVzL0sS1ZafimAEEFARe0UKhv-h93d9YRoLHmQqs1sMxPzS-R6TFfdl87cA",
    },
}


def _parse_posted_at_local(value: str | None, pull_date: str) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None

    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text

    normalized = text.replace("Z", "+00:00")
    if normalized.endswith(" UTC"):
        normalized = normalized[:-4] + "+00:00"
    try:
        return datetime.fromisoformat(normalized).astimezone(timezone.utc).date().isoformat()
    except ValueError:
        pass

    base = date.fromisoformat(pull_date)
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


def parse_posted_at(value: str | None, pull_date: str) -> str | None:
    if _shared_parse_posted_at is not None:
        return _shared_parse_posted_at(value, pull_date)
    return _parse_posted_at_local(value, pull_date)


def digest_source_job_id(opaque_job_id: str) -> str:
    digest = hashlib.sha256(opaque_job_id.encode("utf-8")).digest()[:8]
    return str(int.from_bytes(digest, "big"))


def board_token_from_via(via: str) -> str:
    token = kebab_case(via or "")
    return token or "unknown"


def _apply_options(job: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in job.get("apply_options") or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        link = str(item.get("link") or "").strip()
        if title or link:
            rows.append({"title": title, "link": link})
    return rows


def choose_url(job: dict[str, Any]) -> str:
    via = str(job.get("via") or "").strip()
    for option in _apply_options(job):
        if option["title"] == via and option["link"]:
            return option["link"]
    return str(job.get("share_link") or "").strip()


def build_description_text(job: dict[str, Any]) -> str:
    parts: list[str] = []
    description = str(job.get("description") or "").strip()
    if description:
        parts.append(description)

    for block in job.get("job_highlights") or []:
        if not isinstance(block, dict):
            continue
        title = str(block.get("title") or "").strip()
        items = [str(item).strip() for item in block.get("items") or [] if str(item).strip()]
        if title:
            parts.append(title)
        parts.extend(items)

    selected_url = choose_url(job)
    unused_links = [option["link"] for option in _apply_options(job) if option["link"] and option["link"] != selected_url]
    if unused_links:
        parts.append("Additional apply options:")
        parts.extend(unused_links)

    return "\n".join(parts).strip()


def _posted_at_chip(job: dict[str, Any]) -> str | None:
    detected = job.get("detected_extensions") if isinstance(job.get("detected_extensions"), dict) else {}
    posted = detected.get("posted_at") if detected else None
    if posted:
        return str(posted)
    for extension in job.get("extensions") or []:
        value = str(extension).strip()
        lower = value.lower()
        if re.search(r"\b(day|days|hour|hours|minute|minutes)\s+ago\b", lower) or lower in {
            "today",
            "yesterday",
            "just posted",
            "just now",
        }:
            return value
    return None


def normalize_serpapi_job(
    job: dict[str, Any],
    *,
    pull_date: str,
    status_updated_at: str,
    prior_jobs: dict[str, dict[str, Any]] | None = None,
    force_status: str | None = None,
    include_raw: bool = True,
) -> dict[str, Any]:
    opaque_job_id = str(job.get("job_id") or "").strip()
    if not opaque_job_id:
        raise ValueError("SerpApi job missing job_id")

    via = str(job.get("via") or "").strip()
    board_token = board_token_from_via(via)
    source_job_id = digest_source_job_id(opaque_job_id)
    job_id = f"serpapi:{board_token}:{source_job_id}"
    prior_index = prior_jobs or {}

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

    location = str(job.get("location") or "").strip()
    extensions = [str(item) for item in job.get("extensions") or [] if item is not None]
    work_location_type = extract_work_location_type(" ".join([location] + extensions), [], None)

    parsed_posted_at = parse_posted_at(_posted_at_chip(job), pull_date)
    if parsed_posted_at is None and job_id in prior_index:
        prior_posted_at = prior_index[job_id].get("posted_at")
        if prior_posted_at:
            parsed_posted_at = str(prior_posted_at)

    record: dict[str, Any] = {
        "id": job_id,
        "source_job_id": source_job_id,
        "status": status,
        "title": str(job.get("title") or "").strip(),
        "company": str(job.get("company_name") or "").strip(),
        "location": location,
        "work_location_type": work_location_type,
        "url": choose_url(job),
        "pulled_at": pull_date,
        "posted_at": parsed_posted_at,
        "status_updated_at": presence_ts,
        "description_text": build_description_text(job),
    }
    if include_raw:
        detected = job.get("detected_extensions") if isinstance(job.get("detected_extensions"), dict) else {}
        record["raw"] = {
            "serpapi_job_id": opaque_job_id,
            "via": via,
            "apply_options": _apply_options(job),
            "detected_extensions": {
                key: detected.get(key)
                for key in ("posted_at", "salary", "schedule_type")
                if detected.get(key) is not None
            },
        }
    return record


__all__ = [
    "DATE_POSTED_CATALOG",
    "board_token_from_via",
    "build_description_text",
    "choose_url",
    "digest_source_job_id",
    "normalize_serpapi_job",
    "parse_posted_at",
]
