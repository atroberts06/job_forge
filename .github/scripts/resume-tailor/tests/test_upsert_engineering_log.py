"""upsert_engineering_log.py mints sections 1-3 from a tailor-request row."""

from __future__ import annotations

import json
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = TESTS_DIR.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from upsert_engineering_log import (  # noqa: E402
    RESEARCH_PLACEHOLDER,
    SECTION_4_PLACEHOLDER,
    THEME_PLACEHOLDER,
    main,
    upsert_engineering_log,
)

QUEUE_FIXTURE = (
    TESTS_DIR / "fixtures" / "queue" / "c1d2e3f4a5b6789012345678abcdef01-tailor-request.json"
)


def _sandbox(tmp_path: Path) -> Path:
    sandbox = tmp_path / "repo" / ".ai" / "history" / "resume-tailor" / "lts" / "solution-architect"
    sandbox.mkdir(parents=True)
    return sandbox


def test_upsert_writes_queue_row_sections_and_placeholders(tmp_path: Path):
    sandbox = _sandbox(tmp_path)
    dest = upsert_engineering_log(
        sandbox,
        QUEUE_FIXTURE,
        job_id="greenhouse:lts:100",
        timestamp="2026-09-07T13:00:00Z",
    )
    text = dest.read_text(encoding="utf-8")
    assert dest == sandbox / "engineering-log.md"
    assert "# Engineering Log: LTS - Solution Architect" in text
    assert "Timestamp: 2026-09-07T13:00:00Z" in text
    assert "Queue analysis decision `approved`" in text
    assert "Locked skills evidence Salesforce" in text
    assert "**Salesforce** (`preferred`, `met`)" in text
    assert RESEARCH_PLACEHOLDER in text
    assert text.count(RESEARCH_PLACEHOLDER) == 2
    assert "## 4. Core Modifications Detail" in text
    assert SECTION_4_PLACEHOLDER in text
    assert "### Core Strategic Themes & Alignment" in text
    assert "**JOB_SKILL_1:**" in text
    assert THEME_PLACEHOLDER in text
    assert "analyses/" not in text
    assert "WebSearch" in RESEARCH_PLACEHOLDER


def test_upsert_lists_unmet_mandatory(tmp_path: Path):
    sandbox = _sandbox(tmp_path)
    queue = tmp_path / "queue.json"
    payload = json.loads(QUEUE_FIXTURE.read_text(encoding="utf-8"))
    payload["jobs"][0]["unmet_mandatory"] = [
        {"normalized": "10+ years Palantir", "note": "Not in locked job history."}
    ]
    queue.write_text(json.dumps(payload), encoding="utf-8")
    text = upsert_engineering_log(sandbox, queue, job_id="greenhouse:lts:100").read_text(
        encoding="utf-8"
    )
    assert "**10+ years Palantir:** Not in locked job history." in text


def test_job_id_txt_selects_row_when_flag_omitted(tmp_path: Path):
    sandbox = _sandbox(tmp_path)
    (sandbox / "job-id.txt").write_text("greenhouse:lts:100\n", encoding="utf-8")
    dest = upsert_engineering_log(sandbox, QUEUE_FIXTURE)
    assert "LTS - Solution Architect" in dest.read_text(encoding="utf-8")


def test_single_job_queue_does_not_need_job_id(tmp_path: Path):
    sandbox = _sandbox(tmp_path)
    dest = upsert_engineering_log(sandbox, QUEUE_FIXTURE)
    assert "Salesforce" in dest.read_text(encoding="utf-8")


def test_multi_job_queue_requires_job_id(tmp_path: Path):
    sandbox = _sandbox(tmp_path)
    queue = tmp_path / "queue.json"
    payload = json.loads(QUEUE_FIXTURE.read_text(encoding="utf-8"))
    extra = dict(payload["jobs"][0])
    extra["id"] = "greenhouse:lts:200"
    extra["title"] = "Enterprise Architect"
    payload["jobs"].append(extra)
    queue.write_text(json.dumps(payload), encoding="utf-8")
    assert main(["--sandbox", str(sandbox), "--queue-file", str(queue)]) == 1
    assert not (sandbox / "engineering-log.md").exists()


def test_missing_job_id_is_fail_closed(tmp_path: Path):
    sandbox = _sandbox(tmp_path)
    assert (
        main(
            [
                "--sandbox",
                str(sandbox),
                "--queue-file",
                str(QUEUE_FIXTURE),
                "--job-id",
                "greenhouse:missing:1",
            ]
        )
        == 1
    )
    assert not (sandbox / "engineering-log.md").exists()


def test_cli_writes_log(tmp_path: Path):
    sandbox = _sandbox(tmp_path)
    assert (
        main(
            [
                "--sandbox",
                str(sandbox),
                "--queue-file",
                str(QUEUE_FIXTURE),
                "--job-id",
                "greenhouse:lts:100",
            ]
        )
        == 0
    )
    assert (sandbox / "engineering-log.md").is_file()


def test_script_lives_on_allowlisted_path():
    assert (SCRIPTS_DIR / "upsert_engineering_log.py").is_file()


def test_upsert_writes_core_themes_from_queue_row(tmp_path: Path):
    sandbox = _sandbox(tmp_path)
    queue = tmp_path / "queue.json"
    payload = json.loads(QUEUE_FIXTURE.read_text(encoding="utf-8"))
    payload["jobs"][0]["core_themes"] = {
        "job_skill_1": "Salesforce Education Cloud",
        "job_skill_2": "Systems Integration",
        "job_skill_3": "Cloud Strategy",
        "strength_1": "Enterprise Architecture Governance",
        "strength_2": "Cross-functional Team Leadership",
        "strength_3": "End-to-End Migration Execution",
        "opening_hook": "I bring Salesforce architecture leadership to LTS.",
    }
    queue.write_text(json.dumps(payload), encoding="utf-8")
    text = upsert_engineering_log(sandbox, queue, job_id="greenhouse:lts:100").read_text(
        encoding="utf-8"
    )
    assert "### Core Strategic Themes & Alignment" in text
    assert "**JOB_SKILL_1:** Salesforce Education Cloud" in text
    assert "**STRENGTH_2:** Cross-functional Team Leadership" in text
    assert "**OPENING_HOOK:** I bring Salesforce architecture leadership to LTS." in text
    assert THEME_PLACEHOLDER not in text
