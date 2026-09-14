"""Map TalentBrew list cards and job-detail HTML to the locked job-search model."""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin

from greenhouse.normalize import html_to_text, parse_posted_at

PLATFORM = "talentbrew"
PERSIST_WORKDAY_REQUISITION_ID = True
_REQ_RE = re.compile(r"^R[0-9]+$")
_JOB_HREF_RE = re.compile(r"^/job/[^?]+")
_OVERVIEW_LABELS = {
    "category": "category",
    "experience": "experience",
    "primary address": "primary_address",
}


class _ListCardParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.cards: list[dict[str, str]] = []
        self._li_depth = 0
        self._in_job_a = False
        self._a_depth = 0
        self._current: dict[str, str] | None = None
        self._capture: str | None = None
        self._buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_d = {k: (v or "") for k, v in attrs}
        classes = set((attrs_d.get("class") or "").split())
        if tag == "li":
            if self._li_depth == 0:
                self._current = {}
            self._li_depth += 1
        if self._li_depth and not self._in_job_a and tag == "a":
            href = attrs_d.get("href") or ""
            if href.startswith("/job/"):
                self._in_job_a = True
                self._a_depth = 1
                assert self._current is not None
                self._current["href"] = href.split("?", 1)[0]
                self._current["data_job_id"] = attrs_d.get("data-job-id") or ""
                return
        if self._in_job_a:
            self._a_depth += 1
            if tag == "h2":
                self._start_capture("title")
            elif "job-location" in classes:
                self._start_capture("location")
            elif "job-date-posted" in classes:
                self._start_capture("posted")

    def handle_endtag(self, tag: str) -> None:
        if self._capture and tag in {"h2", "span", "div"}:
            self._finish_capture()
        if self._in_job_a:
            self._a_depth -= 1
            if self._a_depth <= 0:
                self._in_job_a = False
        if tag == "li" and self._li_depth:
            self._li_depth -= 1
            if self._li_depth == 0 and self._current and self._current.get("href"):
                self.cards.append(self._current)
            if self._li_depth == 0:
                self._current = None

    def handle_data(self, data: str) -> None:
        if self._capture:
            text = data.strip()
            if text:
                self._buf.append(text)

    def _start_capture(self, name: str) -> None:
        self._finish_capture()
        self._capture = name
        self._buf = []

    def _finish_capture(self) -> None:
        if not self._capture or self._current is None:
            self._capture = None
            self._buf = []
            return
        text = " ".join(self._buf).strip()
        if text:
            self._current[self._capture] = text
        self._capture = None
        self._buf = []


class _FacetParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.by_display: dict[str, dict[str, str]] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_d = {k.lower(): (v or "") for k, v in attrs}
        display = (
            attrs_d.get("data-display")
            or attrs_d.get("data-facet-display")
            or ""
        ).strip()
        facet_id = (attrs_d.get("data-id") or attrs_d.get("data-facet-id") or "").strip()
        facet_type = (
            attrs_d.get("data-facet-type")
            or attrs_d.get("data-facettype")
            or attrs_d.get("data-facettype")
            or ""
        ).strip()
        field_name = (
            attrs_d.get("data-field-name")
            or attrs_d.get("data-fieldname")
            or attrs_d.get("data-custom-facet-name")
            or ""
        ).strip()
        if display and facet_id:
            self.by_display[display] = {
                "id": facet_id,
                "facet_type": facet_type,
                "field_name": field_name,
                "display": display,
            }


class _DetailParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.meta: dict[str, str] = {}
        self.html_attrs: dict[str, str] = {}
        self.json_ld_chunks: list[str] = []
        self.job_id_text = ""
        self.job_date_text = ""
        self.header_location = ""
        self.h1 = ""
        self.apply_url = ""
        self.section_data_job_id = ""
        self.overview: dict[str, str] = {}
        self.ats_text_parts: list[str] = []
        self._in_script = False
        self._script_type = ""
        self._script_buf: list[str] = []
        self._capture: str | None = None
        self._buf: list[str] = []
        self._in_ats = 0
        self._pending_overview: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_d = {k: (v or "") for k, v in attrs}
        classes = set((attrs_d.get("class") or "").split())
        if tag == "html":
            self.html_attrs = {k: (v or "") for k, v in attrs}
        if tag == "meta":
            name = (attrs_d.get("name") or attrs_d.get("property") or "").strip()
            content = (attrs_d.get("content") or "").strip()
            if name and content:
                self.meta[name] = content
        if tag == "script":
            self._in_script = True
            self._script_type = (attrs_d.get("type") or "").strip().lower()
            self._script_buf = []
        if tag == "section" and (attrs_d.get("data-job-id") or ""):
            self.section_data_job_id = attrs_d.get("data-job-id") or ""
        if "ats-description" in classes:
            self._in_ats += 1
        if tag == "h1":
            self._start_capture("h1")
        elif "job-id" in classes and "job-info" in classes:
            self._start_capture("job_id")
        elif "job-date" in classes and "job-info" in classes:
            self._start_capture("job_date")
        elif "job-location" in classes:
            self._start_capture("header_location")
        if tag == "a" and "job-apply" in classes and attrs_d.get("data-apply-url"):
            self.apply_url = attrs_d["data-apply-url"]
        overview_key = (attrs_d.get("data-overview") or "").strip()
        if overview_key:
            self._start_capture(f"overview:{overview_key}")

    def handle_endtag(self, tag: str) -> None:
        if self._capture and tag in {"h1", "span", "div", "p", "dd", "td"}:
            self._finish_capture()
        if tag == "script" and self._in_script:
            if "ld+json" in self._script_type:
                chunk = "".join(self._script_buf).strip()
                if chunk:
                    self.json_ld_chunks.append(chunk)
            self._in_script = False
            self._script_type = ""
            self._script_buf = []
        if tag in {"div", "section"} and self._in_ats:
            self._in_ats = max(0, self._in_ats - 1)

    def handle_data(self, data: str) -> None:
        if self._in_script:
            self._script_buf.append(data)
            return
        text = data.strip()
        if self._in_ats and text:
            self.ats_text_parts.append(text)
        if self._capture and text:
            self._buf.append(text)
        if text:
            label = text.lower().rstrip(":")
            if label in _OVERVIEW_LABELS:
                self._pending_overview = _OVERVIEW_LABELS[label]
            elif self._pending_overview and self._pending_overview not in self.overview:
                self.overview[self._pending_overview] = text
                self._pending_overview = None

    def _start_capture(self, name: str) -> None:
        self._finish_capture()
        self._capture = name
        self._buf = []

    def _finish_capture(self) -> None:
        if not self._capture:
            return
        text = " ".join(self._buf).strip()
        if text:
            if self._capture == "h1":
                self.h1 = text
            elif self._capture == "job_id":
                self.job_id_text = text
            elif self._capture == "job_date":
                self.job_date_text = text
            elif self._capture == "header_location":
                self.header_location = text
            elif self._capture.startswith("overview:"):
                self.overview[self._capture.split(":", 1)[1]] = text
        self._capture = None
        self._buf = []


def parse_list_cards(results_html: str) -> list[dict[str, str]]:
    parser = _ListCardParser()
    parser.feed(results_html or "")
    parser.close()
    return parser.cards


def parse_job_href(href: str) -> tuple[str, str] | None:
    path = (href or "").split("?", 1)[0].rstrip("/")
    if not path.startswith("/job/"):
        return None
    parts = [p for p in path.split("/") if p]
    if len(parts) < 5:
        return None
    org_id, seq = parts[-2], parts[-1]
    if not seq.isdigit() or not org_id:
        return None
    return org_id, seq


def accepted_list_card(card: dict[str, str]) -> dict[str, str] | None:
    href = card.get("href") or ""
    data_job_id = (card.get("data_job_id") or "").strip()
    parsed = parse_job_href(href)
    if parsed is None or not data_job_id:
        return None
    org_id, seq = parsed
    if seq != data_job_id:
        return None
    out = dict(card)
    out["org_id"] = org_id
    out["source_job_id"] = seq
    return out


def parse_facet_catalog(filters_html: str) -> dict[str, dict[str, str]]:
    parser = _FacetParser()
    parser.feed(filters_html or "")
    parser.close()
    return parser.by_display


def resolve_facet_filters(
    facets: dict[str, Any],
    catalog: dict[str, dict[str, str]],
) -> list[dict[str, str]]:
    resolved: list[dict[str, str]] = []
    for _group, raw in (facets or {}).items():
        if raw is None:
            continue
        if not isinstance(raw, list):
            raise RuntimeError(f"Facet {_group!r} must be null or an array of labels")
        for label in raw:
            text = str(label).strip()
            if not text:
                raise RuntimeError(f"Facet {_group!r} contains an empty label")
            match = catalog.get(text)
            if match is None:
                raise RuntimeError(f"Unknown TalentBrew facet label {text!r} (fail closed)")
            resolved.append(match)
    return resolved


def parse_json_ld_jobposting(chunks: list[str]) -> dict[str, Any] | None:
    for chunk in chunks:
        try:
            data = json.loads(chunk)
        except json.JSONDecodeError:
            continue
        candidates = data if isinstance(data, list) else [data]
        for item in candidates:
            if isinstance(item, dict) and item.get("@type") == "JobPosting":
                return item
            if isinstance(item, dict) and isinstance(item.get("@graph"), list):
                for node in item["@graph"]:
                    if isinstance(node, dict) and node.get("@type") == "JobPosting":
                        return node
    return None


def parse_workday_requisition_id(detail: dict[str, Any]) -> str | None:
    candidates = [
        str(detail.get("span_job_id") or "").strip(),
        str(detail.get("meta_job_ats_req_id") or "").strip(),
        str(detail.get("json_ld_identifier") or "").strip(),
    ]
    for value in candidates:
        if _REQ_RE.fullmatch(value):
            return value
    return None


def _html_remote_facet(html_attrs: dict[str, str]) -> str | None:
    for key, value in html_attrs.items():
        lowered = key.lower()
        if lowered == "custom_fields.remote":
            return value.strip() or None
        if lowered.startswith("custom_fields.remote-") or lowered.startswith("custom_fields.remote"):
            token = key.split("Remote", 1)[-1].lstrip("-_ ")
            return (token or value).strip() or None
    return None


def extract_arrangement(
    *,
    title: str,
    primary_address: str,
    header_location: str,
    html_remote_facet: str | None,
    json_ld: dict[str, Any] | None,
) -> str:
    blobs = [primary_address or "", header_location or ""]
    for blob in blobs:
        parts = [p.strip() for p in blob.split("|")]
        if any(p.lower() == "remote" for p in parts):
            return "remote"
    locations = (json_ld or {}).get("jobLocation") if json_ld else None
    if isinstance(locations, dict):
        locations = [locations]
    if isinstance(locations, list):
        for loc in locations:
            if not isinstance(loc, dict):
                continue
            address = loc.get("address") if isinstance(loc.get("address"), dict) else loc
            country = str((address or {}).get("addressCountry") or "")
            if country.strip().lower() == "remote":
                return "remote"
    facet = (html_remote_facet or "").strip().lower().replace("_", "-")
    if facet in {"not-remote", "not remote"}:
        return "onsite"
    if facet in {"remote"}:
        return "remote"
    if facet in {"remote-eligible", "remote eligible"}:
        return "remote"
    title_l = title.lower()
    if "(remote)" in title_l or "remote eligible" in title_l:
        return "remote"
    return "unknown"


def parse_detail_page(html: str) -> dict[str, Any]:
    parser = _DetailParser()
    parser.feed(html or "")
    parser.close()
    json_ld = parse_json_ld_jobposting(parser.json_ld_chunks)
    html_remote = _html_remote_facet(parser.html_attrs)
    identifier = ""
    date_posted_ld = ""
    description_ld = ""
    if json_ld:
        raw_id = json_ld.get("identifier")
        if isinstance(raw_id, dict):
            identifier = str(raw_id.get("value") or raw_id.get("name") or "").strip()
        elif raw_id is not None:
            identifier = str(raw_id).strip()
        date_posted_ld = str(json_ld.get("datePosted") or "").strip()
        description_ld = str(json_ld.get("description") or "")
    ats_text = re.sub(r"\s+", " ", " ".join(parser.ats_text_parts)).strip()
    if not ats_text and description_ld:
        ats_text = html_to_text(description_ld)
    apply_url = (
        parser.apply_url
        or parser.meta.get("search-job-apply-url")
        or ""
    )
    return {
        "span_job_id": parser.job_id_text,
        "meta_job_ats_req_id": parser.meta.get("job-ats-req-id") or "",
        "json_ld_identifier": identifier,
        "json_ld": json_ld,
        "date_posted_ld": date_posted_ld,
        "description_text": ats_text,
        "h1": parser.h1,
        "header_location": parser.header_location,
        "category": parser.overview.get("category") or "",
        "experience": parser.overview.get("experience") or "",
        "primary_address": parser.overview.get("primary_address") or parser.header_location,
        "apply_url": apply_url,
        "html_remote_facet": html_remote,
        "section_data_job_id": parser.section_data_job_id,
        "posted_detail": parser.job_date_text,
    }


def titles_include_all(criteria: dict[str, Any]) -> bool:
    include = ((criteria.get("titles") or {}).get("include") or [])
    return any(str(item).strip().lower() == "all" for item in include)


def criteria_for_matching(criteria: dict[str, Any]) -> dict[str, Any]:
    """Strip the titles.include 'all' sentinel so it never substring-matches."""
    out = dict(criteria)
    titles = dict(criteria.get("titles") or {})
    include = list(titles.get("include") or [])
    if any(str(item).strip().lower() == "all" for item in include):
        titles["include"] = []
    out["titles"] = titles
    return out


def build_job_id(board_token: str, source_job_id: str) -> str:
    return f"{PLATFORM}:{board_token}:{source_job_id}"


def normalize_talentbrew_job(
    card: dict[str, str],
    detail: dict[str, Any],
    *,
    board_token: str,
    company: str,
    origin: str,
    pull_date: str,
    status_updated_at: str,
    prior_jobs: dict[str, dict[str, Any]] | None = None,
    force_status: str | None = None,
    persist_workday_requisition_id: bool | None = None,
) -> dict[str, Any]:
    accepted = accepted_list_card(card)
    if accepted is None:
        raise ValueError("TalentBrew list card missing agreeing href/data-job-id")
    source_job_id = accepted["source_job_id"]
    job_id = build_job_id(board_token, source_job_id)
    title = (accepted.get("title") or detail.get("h1") or "").strip()
    location = (accepted.get("location") or "").strip()
    url = urljoin(origin.rstrip("/") + "/", accepted["href"].lstrip("/"))
    posted_at = parse_posted_at(accepted.get("posted") or detail.get("posted_detail"), pull_date)
    if posted_at is None:
        posted_at = parse_posted_at(detail.get("date_posted_ld"), pull_date)

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
        if posted_at is None:
            prior_posted = prior_row.get("posted_at")
            if isinstance(prior_posted, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", prior_posted):
                posted_at = prior_posted
    else:
        status = "new"
        presence_ts = status_updated_at

    work_location_type = extract_arrangement(
        title=title,
        primary_address=str(detail.get("primary_address") or ""),
        header_location=str(detail.get("header_location") or ""),
        html_remote_facet=detail.get("html_remote_facet"),
        json_ld=detail.get("json_ld") if isinstance(detail.get("json_ld"), dict) else None,
    )
    raw = {
        "org_id": accepted["org_id"],
        "category": detail.get("category") or "",
        "experience": detail.get("experience") or "",
        "primary_address": detail.get("primary_address") or "",
        "apply_url": detail.get("apply_url") or "",
        "date_posted_ld": detail.get("date_posted_ld") or "",
        "html_remote_facet": detail.get("html_remote_facet") or "",
    }
    record: dict[str, Any] = {
        "id": job_id,
        "source_job_id": source_job_id,
        "status": status,
        "title": title,
        "company": company,
        "location": location,
        "work_location_type": work_location_type,
        "url": url,
        "pulled_at": pull_date,
        "posted_at": posted_at,
        "status_updated_at": presence_ts,
        "description_text": str(detail.get("description_text") or ""),
        "raw": raw,
    }
    persist = (
        PERSIST_WORKDAY_REQUISITION_ID
        if persist_workday_requisition_id is None
        else persist_workday_requisition_id
    )
    parsed_req = parse_workday_requisition_id(detail)
    if persist:
        if parsed_req is None and job_id in prior_index:
            prior_req = prior_index[job_id].get("workday_requisition_id")
            if prior_req is None or (isinstance(prior_req, str) and _REQ_RE.fullmatch(prior_req)):
                parsed_req = prior_req
        record["workday_requisition_id"] = parsed_req
    return record
