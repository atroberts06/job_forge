"""Bounded 5-10 master-prefix chronology (ADR-049)."""

from __future__ import annotations

import sys
from pathlib import Path

_CI_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_CI_DIR))

from common import validate_printed_role_prefix

MASTER = [
    "Team Lead / Acting Enterprise Architect",
    "Team Lead / Acting Solution Architect",
    "Senior Analyst Enrollment Systems",
    "Associate Application Analyst",
    "Information Technology Systems Analyst",
    "Application Development Systems Analyst",
    "Retail Store Systems Analyst",
    "Store Systems Developer",
    "Consultant",
    "Associate Technical Support Analyst & Account Coordinator",
]
EXCLUDED = ["IT Systems Consultant", "Director of Information Technology"]


def test_five_and_ten_role_prefixes_pass() -> None:
    assert validate_printed_role_prefix(MASTER, MASTER[:5], EXCLUDED) is None
    assert validate_printed_role_prefix(MASTER, MASTER, EXCLUDED) is None


def test_short_long_gap_reorder_and_excluded_fail() -> None:
    assert validate_printed_role_prefix(MASTER, MASTER[:4], EXCLUDED)
    assert validate_printed_role_prefix(MASTER, MASTER + ["Extra"], EXCLUDED)
    assert validate_printed_role_prefix(
        MASTER, MASTER[:4] + [MASTER[5]], EXCLUDED
    )
    assert validate_printed_role_prefix(
        MASTER, [MASTER[1], MASTER[0], *MASTER[2:5]], EXCLUDED
    )
    assert validate_printed_role_prefix(
        MASTER, MASTER[:4] + ["IT Systems Consultant"], EXCLUDED
    )
    assert validate_printed_role_prefix(
        MASTER, MASTER[:4] + ["Director of Information Technology"], EXCLUDED
    )
