"""Prefix, bullet-count, and theme-colon validation for fill_resume.py."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_DOCX_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_DOCX_DIR))

import fill_resume as filler

MASTER_TITLES = [
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


def _resume(path: Path, titles: list[str], bullets: list[list[str]]) -> Path:
    lines: list[str] = []
    for title, role_bullets in zip(titles, bullets, strict=True):
        lines.append(f"## {title}")
        lines.extend(f"- {bullet}" for bullet in role_bullets)
        lines.append("")
    lines.extend(["## Skills", "- Enterprise Architecture", ""])
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _themed(count: int) -> list[str]:
    return [f"Theme {index}: Locked result {index}." for index in range(1, count + 1)]


def _roles(titles: list[str], bullets_per_role: int = 3) -> list[dict]:
    return [
        {"title": title, "bullets": _themed(bullets_per_role)} for title in titles
    ]


def test_parse_accepts_one_and_five_bullets(tmp_path: Path) -> None:
    path = _resume(
        tmp_path / "one.md",
        MASTER_TITLES[:5],
        [_themed(3), _themed(3), _themed(3), _themed(3), _themed(1)],
    )
    roles, _skills = filler.parse_tailored_resume(path)
    assert [len(role["bullets"]) for role in roles] == [3, 3, 3, 3, 1]

    path = _resume(
        tmp_path / "five.md",
        MASTER_TITLES[:5],
        [_themed(5) for _ in MASTER_TITLES[:5]],
    )
    roles, _skills = filler.parse_tailored_resume(path)
    assert all(len(role["bullets"]) == 5 for role in roles)


def test_parse_rejects_zero_and_six_bullets(tmp_path: Path) -> None:
    path = _resume(
        tmp_path / "zero.md",
        MASTER_TITLES[:5],
        [_themed(3), _themed(3), _themed(3), _themed(3), []],
    )
    with pytest.raises(filler.FillError, match="required 1-5"):
        filler.parse_tailored_resume(path)

    path = _resume(
        tmp_path / "six.md",
        MASTER_TITLES[:5],
        [_themed(3), _themed(3), _themed(3), _themed(3), _themed(6)],
    )
    with pytest.raises(filler.FillError, match="required 1-5"):
        filler.parse_tailored_resume(path)


def test_parse_rejects_missing_theme_colon(tmp_path: Path) -> None:
    path = _resume(
        tmp_path / "nocolon.md",
        MASTER_TITLES[:5],
        [_themed(3), _themed(3), _themed(3), _themed(3), ["No theme here"]],
    )
    with pytest.raises(filler.FillError, match="theme before the first colon"):
        filler.parse_tailored_resume(path)


def test_prefix_accepts_n5_and_n10() -> None:
    history = {
        str(index): {"title": title, "company": "Co", "location": "Loc", "start_date": "1/2000", "end_date": "2/2000"}
        for index, title in enumerate(MASTER_TITLES, start=1)
    }
    history["11"] = {"title": "IT Systems Consultant"}
    history["12"] = {"title": "Director of Information Technology"}
    filler.tailored_roles_by_prefix(_roles(MASTER_TITLES[:5]), history, MASTER_TITLES)
    matched = filler.tailored_roles_by_prefix(
        _roles(MASTER_TITLES), history, MASTER_TITLES
    )
    assert list(matched) == [str(index) for index in range(1, 11)]


@pytest.mark.parametrize(
    "titles, match",
    [
        (MASTER_TITLES[:4], "required consecutive prefix"),
        (MASTER_TITLES + ["Extra Role"], "required consecutive prefix"),
        (MASTER_TITLES[:4] + [MASTER_TITLES[5]], "consecutive master-template prefix"),
        ([MASTER_TITLES[1], MASTER_TITLES[0], *MASTER_TITLES[2:5]], "consecutive master-template prefix"),
        (MASTER_TITLES[:4] + ["IT Systems Consultant"], "consecutive master-template prefix"),
        (MASTER_TITLES[:4] + ["Director of Information Technology"], "consecutive master-template prefix"),
    ],
)
def test_prefix_rejects_invalid_sets(titles: list[str], match: str) -> None:
    history = {
        str(index): {"title": title, "company": "Co", "location": "Loc", "start_date": "1/2000", "end_date": "2/2000"}
        for index, title in enumerate(MASTER_TITLES, start=1)
    }
    history["11"] = {"title": "IT Systems Consultant"}
    history["12"] = {"title": "Director of Information Technology"}
    with pytest.raises(filler.FillError, match=match):
        filler.tailored_roles_by_prefix(_roles(titles), history, MASTER_TITLES)


def _projects(entries: dict | None = None, pid: str = "prj_001") -> dict:
    payload = {"id": pid}
    if entries is None:
        payload["1"] = {"title": None, "summary": None}
    else:
        payload.update(entries)
    return payload


def test_projects_accepts_null_populated_and_multiple_entries() -> None:
    filler.validate_projects_entries(_projects())
    filler.validate_projects_entries(
        _projects({"1": {"title": "One", "summary": "First."}, "2": {"title": "Two", "summary": "Second."}})
    )
    filler.validate_projects_entries(
        _projects({
            "1": {"title": "One", "url": "https://example.com/one", "summary": "First."},
            "2": {"title": "Two", "url": None, "summary": "Second."},
        })
    )


def test_projects_rejects_partial_title_or_summary() -> None:
    with pytest.raises(filler.FillError, match="both title and summary"):
        filler.validate_projects_entries(_projects({"1": {"title": "Only title", "summary": None}}))
    with pytest.raises(filler.FillError, match="both title and summary"):
        filler.validate_projects_entries(_projects({"1": {"title": None, "summary": "Only summary"}}))


def test_projects_rejects_malformed_entry() -> None:
    with pytest.raises(filler.FillError, match="not an object"):
        filler.validate_projects_entries({"id": "prj_001", "1": "Career Forge"})
    with pytest.raises(filler.FillError, match="missing required field"):
        filler.validate_projects_entries({"id": "prj_001", "1": {"title": "Only title"}})


def test_join_rejects_projects_fk_mismatch() -> None:
    model = filler.load_json(filler.DATA_MODEL)
    bundles = {name: filler.load_json(path) for name, path in filler.section_files().items()}
    bundles["contact"] = {**bundles["contact"], "projects_id": "wrong"}
    with pytest.raises(filler.FillError, match="foreign key mismatch"):
        filler.validate_join(model, bundles)


def test_projects_summery_token_maps_to_summary() -> None:
    bundles = {
        "projects": {
            "id": "prj_001",
            "1": {"title": "Career Forge", "summary": "Pipeline automation."},
        }
    }
    assert filler.resolve_token("PROJECTS_1_TITLE", bundles, {}, []) == "Career Forge"
    assert filler.resolve_token("PROJECTS_1_SUMMERY", bundles, {}, []) == "Pipeline automation."
    assert filler.resolve_token("PROJECTS_1_URL", bundles, {}, []) == ""
    assert filler.resolve_token("PROJECTS_2_TITLE", bundles, {}, []) == ""


def test_projects_resolves_optional_url_and_custom_fields() -> None:
    bundles_with_url = {
        "projects": {
            "id": "prj_001",
            "1": {
                "title": "Career Forge",
                "url": "https://github.com/example/job-forge",
                "summary": "Pipeline automation.",
            },
        }
    }
    assert (
        filler.resolve_token("PROJECTS_1_URL", bundles_with_url, {}, [])
        == "https://github.com/example/job-forge"
    )
    assert filler.resolve_token("PROJECTS_1_CUSTOM_FIELD", bundles_with_url, {}, []) == ""
