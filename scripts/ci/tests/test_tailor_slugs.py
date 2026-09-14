"""Queue-invoked tailor slug suffix (ADR-045)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_CI_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_CI_DIR))

from common import kebab_case, source_job_id_suffix, tailor_queue_slugs


def test_kebab_case_unchanged_for_company_tokens():
    assert kebab_case("Capital One") == "capital-one"
    assert kebab_case("LTS") == "lts"


def test_source_job_id_suffix_trims_over_ten():
    assert source_job_id_suffix("99173226320") == "9173226320"
    assert source_job_id_suffix("4285142009") == "4285142009"
    assert source_job_id_suffix("100") == "100"


def test_source_job_id_suffix_empty_raises():
    with pytest.raises(ValueError, match="source_job_id"):
        source_job_id_suffix("")
    with pytest.raises(ValueError, match="source_job_id"):
        source_job_id_suffix("   ")


def test_tailor_queue_slugs_always_suffix():
    company, position = tailor_queue_slugs("Capital One", "Lead Data Engineer", "99173226320")
    assert company == "capital-one"
    assert position == "lead-data-engineer-9173226320"


def test_tailor_queue_slugs_never_uses_workday_token():
    company, position = tailor_queue_slugs("Capital One", "Lead Software Engineer", "99806094800")
    assert "r249935" not in position
    assert position == "lead-software-engineer-9806094800"
