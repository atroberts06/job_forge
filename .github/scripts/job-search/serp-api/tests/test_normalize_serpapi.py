"""SerpApi normalization tests."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path


def _load_normalize():
    path = Path(__file__).resolve().parents[1] / "normalize_serpapi.py"
    spec = importlib.util.spec_from_file_location("normalize_serpapi", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_starbucks_normalizes_google_jobs_payload():
    mod = _load_normalize()
    fixture = Path(__file__).resolve().parent / "fixtures" / "jobs_results_sample.json"
    raw = json.loads(fixture.read_text(encoding="utf-8"))["jobs_results"][0]

    normalized = mod.normalize_serpapi_job(
        raw,
        pull_date="2026-01-03",
        status_updated_at="2026-01-03T15:00:00Z",
    )
    digest = str(int.from_bytes(hashlib.sha256(raw["job_id"].encode("utf-8")).digest()[:8], "big"))

    assert normalized["id"] == f"serpapi:indeed:{digest}"
    assert normalized["source_job_id"] == digest
    assert normalized["posted_at"] == "2025-12-30"
    assert normalized["url"] == raw["apply_options"][0]["link"]
    assert "indeed.com/viewjob" in normalized["url"]
    assert normalized["work_location_type"] == "unknown"
    assert normalized["raw"]["serpapi_job_id"] == raw["job_id"]


def test_aramark_normalizes_first_party_via():
    mod = _load_normalize()
    fixture = Path(__file__).resolve().parent / "fixtures" / "jobs_results_sample.json"
    raw = json.loads(fixture.read_text(encoding="utf-8"))["jobs_results"][1]

    normalized = mod.normalize_serpapi_job(
        raw,
        pull_date="2026-01-03",
        status_updated_at="2026-01-03T15:00:00Z",
    )
    digest = str(int.from_bytes(hashlib.sha256(raw["job_id"].encode("utf-8")).digest()[:8], "big"))
    board = mod.board_token_from_via(raw.get("via") or "")

    assert normalized["id"] == f"serpapi:{board}:{digest}"
    assert normalized["company"]
    assert normalized["posted_at"] == "2025-12-30"
    assert normalized["url"]
