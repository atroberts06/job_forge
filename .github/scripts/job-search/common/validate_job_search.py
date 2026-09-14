"""Path-selected fail-closed validation of job-search instance files."""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
from datetime import date, datetime
from pathlib import Path
from typing import Any

_JOB_SEARCH = Path(__file__).resolve().parents[1]
if str(_JOB_SEARCH) not in sys.path:
    sys.path.insert(0, str(_JOB_SEARCH))

from jsonschema import Draft7Validator, FormatChecker

_UTC_Z_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SOURCE_JOB_ID_RE = re.compile(r"^[0-9]+$")
_WORKDAY_REQ_RE = re.compile(r"^R[0-9]+$")
_JSC_003_GOOGLE_ONLY = frozenset(
    {
        "search_query",
        "date_posted",
        "max_searches",
        "industry_query",
        "google_domain",
        "next_page_token",
        "google_filter_token",
        "location",
        "keywords",
        "match_mode",
    }
)
_JSC_003_INT_MIN = {
    "records_per_page": 1,
    "timeout_seconds": 1,
    "request_delay_ms": 0,
    "max_retries": 0,
}
_WINDOWS_ILLEGAL = set('<>:"/\\|?*')
ANALYSIS_SUFFIX = "-analysis.json"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def repo_root_from_here() -> Path:
    # .../.github/scripts/job-search/common/validate_job_search.py -> repo root
    return Path(__file__).resolve().parents[4]


def is_ymd(value: str) -> bool:
    if not _DATE_RE.fullmatch(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def is_utc_z(value: str) -> bool:
    if not _UTC_Z_RE.match(value):
        return False
    try:
        datetime.strptime(value.replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S%z")
    except ValueError:
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return False
    return True


def encode_job_id(job_id: str) -> str:
    return job_id.replace(":", "-")


def parse_analysis_filename(name: str) -> tuple[str, str, str] | None:
    """Return (platform, board_token, source_job_id) or None if unparseable."""
    if not name.endswith(ANALYSIS_SUFFIX):
        return None
    stem = name[: -len(ANALYSIS_SUFFIX)]
    parts = stem.split("-")
    if len(parts) < 3:
        return None
    platform = parts[0]
    source_job_id = parts[-1]
    board_token = "-".join(parts[1:-1])
    if not platform or not board_token or not source_job_id:
        return None
    if "-" in platform:
        return None
    if not _SOURCE_JOB_ID_RE.fullmatch(source_job_id):
        return None
    if any(ch in _WINDOWS_ILLEGAL or ch == ":" for ch in board_token):
        return None
    return platform, board_token, source_job_id


ATS_PLATFORMS = frozenset({"greenhouse", "lever", "ashby", "unknown"})
_KEBAB_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_NAME_SPLIT_RE = re.compile(r"[^a-z0-9]+")
_CAREER_URL_STOPWORDS = frozenset(
    {"inc", "llc", "ltd", "corp", "co", "the", "and", "of", "for", "a", "an", "company"}
)
_NAME_TOKEN_MIN = 4


def url_contains_ats_identity(url: str, platform: str, board_token: str) -> bool:
    """True when url contains both the ATS platform name and board token."""
    haystack = url.strip().lower()
    platform_key = platform.strip().lower()
    token_key = board_token.strip().lower()
    if not haystack or not platform_key or not token_key:
        return False
    return platform_key in haystack and token_key in haystack


def company_name_needles(name: str) -> set[str]:
    """Distinctive fragments of an employer name used to accept a careers URL."""
    tokens = [part for part in _NAME_SPLIT_RE.split(name.strip().lower()) if part]
    needles: set[str] = set()
    if tokens:
        slug = "-".join(tokens)
        needles.add(slug)
        needles.add("".join(tokens))
    long_tokens = [token for token in tokens if token not in _CAREER_URL_STOPWORDS and len(token) >= _NAME_TOKEN_MIN]
    short_keep = [token for token in tokens if token not in _CAREER_URL_STOPWORDS]
    for token in long_tokens or short_keep:
        needles.add(token)
    for left, right in zip(tokens, tokens[1:]):
        if left in _CAREER_URL_STOPWORDS or right in _CAREER_URL_STOPWORDS:
            continue
        needles.add(f"{left}-{right}")
        needles.add(f"{left}{right}")
    needles.discard("")
    return needles


def career_site_origin(url: str) -> str:
    """Return scheme://host with path, query, and fragment removed. Empty if not http(s)."""
    text = url.strip()
    if not text:
        return ""
    parsed = urllib.parse.urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    host = parsed.netloc.lower()
    if parsed.scheme == "https" and host.endswith(":443"):
        host = host[: -len(":443")]
    elif parsed.scheme == "http" and host.endswith(":80"):
        host = host[: -len(":80")]
    return f"{parsed.scheme}://{host}"


def url_contains_company_name(url: str, company_name: str) -> bool:
    """True when url contains some distinctive part of the employer name."""
    haystack = url.strip().lower()
    if not haystack:
        return False
    return any(needle in haystack for needle in company_name_needles(company_name))


def select_schema_ref(path: Path) -> str:
    name = path.name
    posix = path.as_posix()
    if name == "locked-job-search-criteria.json":
        return "CRITERIA_FILE"
    if name == "approved-jobs.json":
        return "APPROVED_JOBS"
    if name.endswith(ANALYSIS_SUFFIX) and "/analyses/" in posix.replace("\\", "/"):
        return "ANALYSIS_FILE"
    if name == "jobs.json":
        return "PULL_FILE"
    if name == "companies.json":
        return "COMPANIES_FILE"
    raise ValueError(f"cannot select schema $ref for path: {path}")


def schema_for_ref(full_schema: dict[str, Any], ref_name: str) -> dict[str, Any]:
    defs = full_schema.get("$defs") or full_schema.get("definitions")
    if not isinstance(defs, dict) or ref_name not in defs:
        raise ValueError(f"schema missing $defs.{ref_name}")
    return {
        "$schema": full_schema.get("$schema", "https://json-schema.org/draft-07/schema#"),
        "$defs": defs,
        "allOf": [{"$ref": f"#/$defs/{ref_name}"}],
    }


def validate_companies_semantic(envelope: dict[str, Any]) -> list[str]:
    """Fail-closed catalog checks. Report company id and source slot."""
    errors: list[str] = []
    companies = envelope.get("companies")
    if not isinstance(companies, list):
        return ["companies must be an array"]

    seen_ids: set[str] = set()
    seen_tokens: dict[tuple[str, str], str] = {}

    for index, row in enumerate(companies):
        if not isinstance(row, dict):
            errors.append(f"companies[{index}]: must be an object")
            continue
        company_id = str(row.get("id") or "")
        loc = f"companies[{index}] id={company_id!r}" if company_id else f"companies[{index}]"

        if not company_id or not _KEBAB_RE.fullmatch(company_id):
            errors.append(f"{loc}: id must be kebab-case")
        elif company_id in seen_ids:
            errors.append(f"{loc}: duplicate id {company_id!r}")
        else:
            seen_ids.add(company_id)

        industries = row.get("industries")
        if not isinstance(industries, list):
            errors.append(f"{loc}: industries must be an array")
        else:
            seen_ind: set[str] = set()
            for i, tag in enumerate(industries):
                if not isinstance(tag, str) or not tag.strip():
                    errors.append(f"{loc}: industries[{i}]: must be a non-empty string")
                    continue
                if tag in seen_ind:
                    errors.append(f"{loc}: industries[{i}]: duplicate tag {tag!r}")
                else:
                    seen_ind.add(tag)

        company_slot = row.get("company")
        if isinstance(company_slot, dict):
            slot_platform = str(company_slot.get("platform") or "")
            slot_token = str(company_slot.get("board_token") or "")
            if slot_platform != company_id or slot_token != company_id:
                errors.append(
                    f"{loc} slot=company: platform and board_token must equal parent id {company_id!r}"
                )

        ats = row.get("ats")
        if isinstance(ats, dict):
            ats_platform = str(ats.get("platform") or "")
            ats_enabled = ats.get("enabled") is True
            ats_source = str(ats.get("source") or "")
            if ats_enabled and ats_platform not in ATS_PLATFORMS:
                errors.append(
                    f"{loc} slot=ats: platform must be greenhouse|lever|ashby|unknown, "
                    f"got {ats_platform!r}"
                )
            elif not ats_enabled and ats_platform and ats_platform not in ATS_PLATFORMS:
                errors.append(
                    f"{loc} slot=ats: platform must be greenhouse|lever|ashby|unknown or empty, "
                    f"got {ats_platform!r}"
                )
            if ats_enabled and not ats_source:
                errors.append(f"{loc} slot=ats: source is required when enabled")
            detected_at = ats.get("detected_at")
            if detected_at is not None and (not isinstance(detected_at, str) or not is_ymd(detected_at)):
                errors.append(f"{loc} slot=ats: detected_at must be YYYY-MM-DD or null")
            ats_career_url = str(ats.get("career_url") or "").strip()
            if ats_career_url and not url_contains_ats_identity(
                ats_career_url, ats_platform, str(ats.get("board_token") or "")
            ):
                errors.append(
                    f"{loc} slot=ats: career_url must contain platform and board_token"
                )

        if isinstance(company_slot, dict):
            detected_at = company_slot.get("detected_at")
            if detected_at is not None and (
                not isinstance(detected_at, str) or not is_ymd(detected_at)
            ):
                errors.append(f"{loc} slot=company: detected_at must be YYYY-MM-DD or null")
            company_career_url = str(company_slot.get("career_url") or "").strip()
            display_name = str(row.get("name") or "")
            if company_career_url:
                origin = career_site_origin(company_career_url)
                if not origin or origin != company_career_url:
                    errors.append(
                        f"{loc} slot=company: career_url must be an origin (scheme://host) with no path or query"
                    )
                elif not url_contains_company_name(company_career_url, display_name):
                    errors.append(
                        f"{loc} slot=company: career_url must contain a distinctive part of the company name"
                    )

        for slot_name in ("ats", "company"):
            slot = row.get(slot_name)
            if not isinstance(slot, dict):
                continue
            platform = str(slot.get("platform") or "").strip()
            token = str(slot.get("board_token") or "").strip()
            if not token:
                continue
            key = (slot_name, platform, token)
            prior = seen_tokens.get(key)
            if prior is not None:
                errors.append(
                    f"{loc} slot={slot_name}: duplicate (platform, board_token) "
                    f"{platform!r}/{token!r} (also {prior})"
                )
            else:
                seen_tokens[key] = f"{loc} slot={slot_name}"

    return errors


def _validate_jsc_003(row: dict[str, Any], loc: str, pipeline: str) -> list[str]:
    errors: list[str] = []
    if pipeline != "talentbrew":
        errors.append(f"{loc}: pipeline must be 'talentbrew'")
    forbidden = sorted(key for key in _JSC_003_GOOGLE_ONLY if key in row)
    if forbidden:
        errors.append(
            f"{loc}: must not contain Google-only or unused keys "
            + ", ".join(repr(key) for key in forbidden)
        )
    for key, minimum in _JSC_003_INT_MIN.items():
        raw = row.get(key)
        if type(raw) is not int or raw < minimum:
            errors.append(f"{loc}: {key} must be an integer >= {minimum}")
    max_pages = row.get("max_pages")
    if max_pages is not None and (type(max_pages) is not int or max_pages < 1):
        errors.append(f"{loc}: max_pages must be null or an integer >= 1")
    codes = row.get("retry_status_codes")
    if not isinstance(codes, list) or not codes or not all(type(item) is int for item in codes):
        errors.append(f"{loc}: retry_status_codes must be a non-empty int array")
    for key in ("search_keywords", "search_location"):
        value = row.get(key)
        if value is not None and not isinstance(value, str):
            errors.append(f"{loc}: {key} must be null or a string")
    facets = row.get("facets")
    if not isinstance(facets, dict):
        errors.append(f"{loc}: facets is required and must be an object")
    else:
        for facet_key, facet_val in facets.items():
            if facet_val is None:
                continue
            if not isinstance(facet_val, list) or not facet_val or not all(
                isinstance(item, str) and item.strip() for item in facet_val
            ):
                errors.append(f"{loc}: facets.{facet_key} must be null or a non-empty-string array")
    return errors


def validate_criteria_semantic(envelope: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    criteria = envelope.get("criteria")
    if not isinstance(criteria, list):
        return ["criteria must be an array"]

    seen_ids: set[str] = set()
    seen_pipelines: set[str] = set()
    greenhouse_row: dict[str, Any] | None = None
    for index, row in enumerate(criteria):
        if not isinstance(row, dict):
            errors.append(f"criteria[{index}]: must be an object")
            continue
        criteria_id = str(row.get("id") or "")
        pipeline = str(row.get("pipeline") or "")
        loc = f"criteria[{index}] id={criteria_id!r}" if criteria_id else f"criteria[{index}]"

        if criteria_id:
            if criteria_id in seen_ids:
                errors.append(f"{loc}: duplicate id {criteria_id!r}")
            else:
                seen_ids.add(criteria_id)
        if pipeline:
            if pipeline in seen_pipelines:
                errors.append(f"{loc}: duplicate pipeline {pipeline!r}")
            else:
                seen_pipelines.add(pipeline)
        if criteria_id == "jsc_001":
            greenhouse_row = row
            if pipeline != "greenhouse":
                errors.append(f"{loc}: pipeline must be 'greenhouse'")
        if criteria_id == "jsc_002":
            if pipeline != "google_jobs":
                errors.append(f"{loc}: pipeline must be 'google_jobs'")
            raw = row.get("max_searches")
            if type(raw) is not int or raw < 1:
                errors.append(f"{loc}: max_searches must be an integer >= 1")
        if criteria_id == "jsc_003":
            errors.extend(_validate_jsc_003(row, loc, pipeline))

    if greenhouse_row is None:
        errors.append("criteria: must contain id='jsc_001' with pipeline='greenhouse'")
    else:
        google_only = {
            "search_query",
            "date_posted",
            "industry_query",
            "google_domain",
            "next_page_token",
            "google_filter_token",
            "location",
            "max_searches",
        }
        present = sorted(key for key in google_only if key in greenhouse_row)
        if present:
            errors.append(
                "criteria id='jsc_001': must not contain Google-only keys "
                + ", ".join(repr(key) for key in present)
            )

    return errors


def company_enabled_boards(envelope: dict[str, Any]) -> list[dict[str, str]]:
    """Pullable company-slot rows: enabled, non-empty board_token, career origin."""
    boards: list[dict[str, str]] = []
    for row in envelope.get("companies") or []:
        if not isinstance(row, dict):
            continue
        slot = row.get("company")
        if not isinstance(slot, dict):
            continue
        if slot.get("enabled") is not True:
            continue
        token = str(slot.get("board_token") or "").strip()
        origin = career_site_origin(str(slot.get("career_url") or ""))
        if not token or not origin:
            continue
        name = str(row.get("name") or token).strip()
        boards.append({"board_token": token, "company": name, "career_url": origin})
    return boards


def greenhouse_ats_boards(envelope: dict[str, Any]) -> list[dict[str, str]]:
    """Pullable Greenhouse ats rows: enabled, platform greenhouse, non-empty board_token."""
    boards: list[dict[str, str]] = []
    for row in envelope.get("companies") or []:
        if not isinstance(row, dict):
            continue
        ats = row.get("ats")
        if not isinstance(ats, dict):
            continue
        if ats.get("enabled") is not True:
            continue
        if str(ats.get("platform") or "") != "greenhouse":
            continue
        token = str(ats.get("board_token") or "").strip()
        if not token:
            continue
        name = str(row.get("name") or token).strip()
        boards.append({"board_token": token, "company": name})
    return boards


def validate_jobs_semantic(envelope: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    platform = str(envelope.get("platform") or "")
    jobs = envelope.get("jobs")
    if not isinstance(jobs, list):
        return ["jobs must be an array"]

    seen_ids: set[str] = set()
    for index, job in enumerate(jobs):
        if not isinstance(job, dict):
            errors.append(f"jobs[{index}]: must be an object")
            continue

        job_id = str(job.get("id") or "")
        source_job_id = str(job.get("source_job_id") or "")
        title = str(job.get("title") or "")
        company = str(job.get("company") or "")
        status_updated_at = str(job.get("status_updated_at") or "")
        posted_at = job.get("posted_at")

        segments = job_id.split(":")
        if len(segments) != 3 or any(not s for s in segments):
            errors.append(
                f"jobs[{index}].id: must be '{{platform}}:{{board_token}}:{{source_job_id}}' "
                f"with three non-empty segments, got {job_id!r}"
            )
        else:
            if segments[0] != platform:
                errors.append(
                    f"jobs[{index}].id: platform segment {segments[0]!r} does not match "
                    f"envelope platform {platform!r}"
                )
            if segments[2] != source_job_id:
                errors.append(
                    f"jobs[{index}].id: trailing segment {segments[2]!r} does not equal "
                    f"source_job_id {source_job_id!r}"
                )

        if job_id:
            if job_id in seen_ids:
                errors.append(f"jobs[{index}].id: duplicate id {job_id!r}")
            else:
                seen_ids.add(job_id)

        if not title.strip():
            errors.append(f"jobs[{index}].title: must be non-empty after trimming")
        if not company.strip():
            errors.append(f"jobs[{index}].company: must be non-empty after trimming")

        if status_updated_at and not is_utc_z(status_updated_at):
            errors.append(
                f"jobs[{index}].status_updated_at: must be UTC with Z suffix, got {status_updated_at!r}"
            )
        if "posted_at" not in job:
            errors.append(f"jobs[{index}].posted_at: required key missing")
        elif posted_at is not None and (not isinstance(posted_at, str) or not _DATE_RE.fullmatch(posted_at)):
            errors.append(f"jobs[{index}].posted_at: must be YYYY-MM-DD or null")

        if platform == "talentbrew":
            if "workday_requisition_id" not in job:
                errors.append(f"jobs[{index}].workday_requisition_id: required on talentbrew")
            else:
                req = job.get("workday_requisition_id")
                if req is not None and (not isinstance(req, str) or not _WORKDAY_REQ_RE.fullmatch(req)):
                    errors.append(
                        f"jobs[{index}].workday_requisition_id: must be ^R[0-9]+$ or null, got {req!r}"
                    )
                elif isinstance(req, str) and req == source_job_id:
                    errors.append(
                        f"jobs[{index}].workday_requisition_id: must not equal source_job_id"
                    )
        elif "workday_requisition_id" in job:
            req = job.get("workday_requisition_id")
            if req is not None and (not isinstance(req, str) or not _WORKDAY_REQ_RE.fullmatch(req)):
                errors.append(
                    f"jobs[{index}].workday_requisition_id: must be ^R[0-9]+$ or null, got {req!r}"
                )

    pulled_at = str(envelope.get("pulled_at") or "")
    if pulled_at and not is_utc_z(pulled_at):
        errors.append(f"pulled_at: must be UTC with Z suffix, got {pulled_at!r}")

    return errors


def _collect_job_ids(repo_root: Path, platform: str) -> set[str]:
    ids: set[str] = set()
    src = repo_root / ".ai" / "history" / "job-search" / platform / "src"
    if not src.is_dir():
        return ids
    for jobs_path in src.glob("*/jobs.json"):
        try:
            data = load_json(jobs_path)
        except (OSError, json.JSONDecodeError):
            continue
        for job in data.get("jobs") or []:
            if isinstance(job, dict) and job.get("id"):
                ids.add(str(job["id"]))
    return ids


def validate_analysis_semantic(
    envelope: dict[str, Any],
    path: Path,
    *,
    repo_root: Path | None,
    require_stub: bool,
) -> list[str]:
    errors: list[str] = []
    parsed = parse_analysis_filename(path.name)
    if parsed is None:
        errors.append(f"filename: must be {{encoded_job_id}}-analysis.json, got {path.name!r}")
        return errors
    platform, board_token, source_job_id = parsed
    expected_id = f"{platform}:{board_token}:{source_job_id}"
    job_id = str(envelope.get("job_id") or "")
    if job_id != expected_id:
        errors.append(
            f"job_id: unsanitized id {job_id!r} does not match filename encoding {expected_id!r}"
        )
    if envelope.get("platform") != platform:
        errors.append(
            f"platform: envelope {envelope.get('platform')!r} does not match filename {platform!r}"
        )

    analyses = envelope.get("analyses")
    if not isinstance(analyses, list) or not analyses:
        errors.append("analyses: must be a non-empty array")
        return errors

    current = [row for row in analyses if isinstance(row, dict) and row.get("is_current") is True]
    if len(current) != 1:
        errors.append("analyses: exactly one row must have is_current true")
    else:
        current_id = current[0].get("analysis_id")
        if envelope.get("analysis_id") != current_id:
            errors.append(
                f"analysis_id: envelope {envelope.get('analysis_id')!r} must equal "
                f"is_current row {current_id!r}"
            )

    seen: set[Any] = set()
    for index, row in enumerate(analyses):
        if not isinstance(row, dict):
            errors.append(f"analyses[{index}]: must be an object")
            continue
        aid = row.get("analysis_id")
        if aid in seen:
            errors.append(f"analyses[{index}].analysis_id: duplicate {aid!r}")
        else:
            seen.add(aid)
        if row.get("job_id") != job_id:
            errors.append(f"analyses[{index}].job_id: must equal envelope job_id")
        pull_date = str(row.get("pull_date") or "")
        if pull_date and not _DATE_RE.fullmatch(pull_date):
            errors.append(f"analyses[{index}].pull_date: must be YYYY-MM-DD")
        analyzed_at = row.get("analyzed_at")
        if analyzed_at is not None and (not isinstance(analyzed_at, str) or not is_utc_z(analyzed_at)):
            errors.append(f"analyses[{index}].analyzed_at: must be UTC with Z suffix or null")
        if row.get("external_context", {}).get("decision_impact") not in (None, "none"):
            errors.append(f"analyses[{index}].external_context.decision_impact: must be none")

    if current:
        current_row = current[0]
        filled = (
            current_row.get("decision") is not None
            or current_row.get("analyzed_at") is not None
            or current_row.get("run_id") is not None
            or envelope.get("analysis_id") not in (0, None)
        )
        if filled and (current_row.get("revision") == 0 or current_row.get("analysis_id") == 0):
            errors.append("fill: revision and analysis_id must not remain 0 after fill")

    if require_stub:
        if envelope.get("analysis_id") != 0:
            errors.append("stub: envelope analysis_id must be 0")
        if len(analyses) != 1:
            errors.append("stub: analyses must contain exactly one row")
        else:
            row = analyses[0]
            if row.get("analysis_id") != 0 or row.get("revision") != 0:
                errors.append("stub: row analysis_id and revision must be 0")
            if row.get("run_id") is not None or row.get("analyzed_at") is not None:
                errors.append("stub: run_id and analyzed_at must be null")
            if row.get("decision") is not None or row.get("justification") is not None:
                errors.append("stub: decision and justification must be null")

    updated_at = str(envelope.get("updated_at") or "")
    if updated_at and not is_utc_z(updated_at):
        errors.append(f"updated_at: must be UTC with Z suffix, got {updated_at!r}")

    if repo_root is not None and job_id:
        known = _collect_job_ids(repo_root, str(envelope.get("platform") or platform))
        if job_id not in known:
            errors.append(f"join: job_id {job_id!r} not found on any dated jobs.json")

    return errors


def validate_approved_semantic(
    envelope: dict[str, Any],
    path: Path,
    *,
    repo_root: Path | None,
) -> list[str]:
    errors: list[str] = []
    jobs = envelope.get("jobs")
    if not isinstance(jobs, list):
        return ["jobs must be an array"]
    platform = str(envelope.get("platform") or "")
    analyses_dir = path.parent / "analyses"
    for index, row in enumerate(jobs):
        if not isinstance(row, dict):
            errors.append(f"jobs[{index}]: must be an object")
            continue
        job_id = str(row.get("id") or "")
        analysis_id = row.get("analysis_id")
        approved_at = str(row.get("approved_at") or "")
        if approved_at and not is_utc_z(approved_at):
            errors.append(f"jobs[{index}].approved_at: must be UTC with Z suffix")
        sidecar = analyses_dir / f"{encode_job_id(job_id)}{ANALYSIS_SUFFIX}"
        if not sidecar.is_file():
            errors.append(f"jobs[{index}]: sidecar missing for {job_id!r}")
            continue
        try:
            sidecar_doc = load_json(sidecar)
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"jobs[{index}]: cannot read sidecar: {exc}")
            continue
        ids = {
            item.get("analysis_id")
            for item in (sidecar_doc.get("analyses") or [])
            if isinstance(item, dict)
        }
        if analysis_id not in ids:
            errors.append(
                f"jobs[{index}].analysis_id: {analysis_id!r} not present in sidecar analyses[]"
            )
    if repo_root is not None:
        known = _collect_job_ids(repo_root, platform)
        for index, row in enumerate(jobs):
            if not isinstance(row, dict):
                continue
            job_id = str(row.get("id") or "")
            if job_id and job_id not in known:
                errors.append(f"jobs[{index}].id: {job_id!r} not found on any dated jobs.json")
    return errors


def validate_document(
    envelope: dict[str, Any],
    path: Path,
    full_schema: dict[str, Any],
    *,
    repo_root: Path | None = None,
    require_stub: bool = False,
) -> list[str]:
    errors: list[str] = []
    try:
        ref_name = select_schema_ref(path)
    except ValueError as exc:
        return [str(exc)]
    try:
        selected = schema_for_ref(full_schema, ref_name)
    except ValueError as exc:
        return [str(exc)]

    validator = Draft7Validator(selected, format_checker=FormatChecker())
    for error in sorted(validator.iter_errors(envelope), key=lambda e: list(e.path)):
        loc = ".".join(str(p) for p in error.path) or "(root)"
        errors.append(f"schema: {loc}: {error.message}")

    if ref_name == "PULL_FILE":
        errors.extend(validate_jobs_semantic(envelope))
    elif ref_name == "CRITERIA_FILE":
        errors.extend(validate_criteria_semantic(envelope))
    elif ref_name == "COMPANIES_FILE":
        errors.extend(validate_companies_semantic(envelope))
    elif ref_name == "ANALYSIS_FILE":
        errors.extend(
            validate_analysis_semantic(
                envelope, path, repo_root=repo_root, require_stub=require_stub
            )
        )
    elif ref_name == "APPROVED_JOBS":
        errors.extend(validate_approved_semantic(envelope, path, repo_root=repo_root))
    return errors


def validate_file(
    instance_path: Path,
    schema_path: Path,
    *,
    repo_root: Path | None = None,
    require_stub: bool = False,
) -> list[str]:
    try:
        envelope = load_json(instance_path)
    except (OSError, json.JSONDecodeError) as exc:
        return [f"cannot read instance file: {exc}"]
    try:
        schema = load_json(schema_path)
    except (OSError, json.JSONDecodeError) as exc:
        return [f"cannot read schema: {exc}"]
    if not isinstance(envelope, dict):
        return ["instance root must be an object"]
    return validate_document(
        envelope,
        instance_path,
        schema,
        repo_root=repo_root,
        require_stub=require_stub,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate a job-search instance file (path-selected $ref, fail-closed)"
    )
    parser.add_argument(
        "instance_file",
        help="Path to jobs.json, approved-jobs.json, companies.json, or *-analysis.json",
    )
    parser.add_argument("--schema", default=None)
    parser.add_argument("--repo-root", default=None)
    parser.add_argument(
        "--require-stub",
        action="store_true",
        help="Require ANALYSIS_FILE to be pull-stub shaped (analysis_id 0 / revision 0)",
    )
    args = parser.parse_args(argv)

    instance_path = Path(args.instance_file).resolve()
    root = Path(args.repo_root).resolve() if args.repo_root else repo_root_from_here()
    schema_path = (
        Path(args.schema).resolve()
        if args.schema
        else root / ".ai" / "guardrails" / "locked-job-search-data-model.json"
    )

    if not instance_path.is_file():
        print(f"ERROR: instance file missing: {instance_path}", file=sys.stderr)
        return 1
    if not schema_path.is_file():
        print(f"ERROR: schema missing: {schema_path}", file=sys.stderr)
        return 1

    errors = validate_file(
        instance_path,
        schema_path,
        repo_root=root,
        require_stub=args.require_stub,
    )
    if errors:
        print(f"Validation FAILED for {instance_path} ({len(errors)} error(s)):", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    print(f"Validation passed: {instance_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
