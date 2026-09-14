"""upsert_job_description.py mints P2-J1 job-description.md from a tailor-request row."""

from __future__ import annotations

import json
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = TESTS_DIR.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from upsert_job_description import (  # noqa: E402
    main,
    upsert_job_description,
)

QUEUE_FIXTURE = (
    TESTS_DIR / "fixtures" / "queue" / "c1d2e3f4a5b6789012345678abcdef01-tailor-request.json"
)
JOB_ID = "greenhouse:lts:100"


def _sandbox(tmp_path: Path) -> Path:
    sandbox = tmp_path / "repo" / ".ai" / "history" / "resume-tailor" / "lts" / "solution-architect"
    sandbox.mkdir(parents=True)
    return sandbox


def _queue_copy() -> dict:
    return json.loads(QUEUE_FIXTURE.read_text(encoding="utf-8"))


def _write_queue(tmp_path: Path, payload: dict) -> Path:
    queue = tmp_path / "queue.json"
    queue.write_text(json.dumps(payload), encoding="utf-8")
    return queue


def test_mint_matches_p2_j1_shape(tmp_path: Path):
    sandbox = _sandbox(tmp_path)
    dest = upsert_job_description(sandbox, QUEUE_FIXTURE, job_id=JOB_ID)
    text = dest.read_text(encoding="utf-8")
    assert dest == sandbox / "job-description.md"
    assert text.startswith("# LTS - Solution Architect\n")
    assert "- **Location:** New York, NY\n" in text
    assert "- **URL:** https://job-boards.greenhouse.io/lts/jobs/100\n" in text
    assert "## Job description\n" in text
    assert "Architect Salesforce and CI/CD." in text
    assert "- **Decision:** approved\n" in text
    assert "- **Justification:** Locked skills evidence Salesforce and enterprise architecture.\n" in text
    assert "## Unmet mandatory requirements\n" in text
    assert "- None\n" in text
    assert "## Mentioned Skills\n" in text
    assert (
        "- **Salesforce** (`preferred`, `met`): Named platform evidenced in locked-skills.json.\n"
        in text
    )
    assert "**10+ years" not in text


def test_empty_lists_render_none(tmp_path: Path):
    sandbox = _sandbox(tmp_path)
    payload = _queue_copy()
    payload["jobs"][0]["unmet_mandatory"] = []
    payload["jobs"][0]["mentioned_skills"] = []
    queue = _write_queue(tmp_path, payload)
    text = upsert_job_description(sandbox, queue, job_id=JOB_ID).read_text(encoding="utf-8")
    unmet_block = text.split("## Unmet mandatory requirements", 1)[1].split("## Mentioned Skills", 1)[0]
    skills_block = text.split("## Mentioned Skills", 1)[1]
    assert unmet_block.count("- None") == 1
    assert skills_block.count("- None") == 1
    assert "**Salesforce**" not in text


def test_nonempty_unmet_is_unbolded(tmp_path: Path):
    sandbox = _sandbox(tmp_path)
    payload = _queue_copy()
    payload["jobs"][0]["unmet_mandatory"] = [
        {"normalized": "10+ years Palantir", "note": "Not in locked job history."}
    ]
    queue = _write_queue(tmp_path, payload)
    text = upsert_job_description(sandbox, queue, job_id=JOB_ID).read_text(encoding="utf-8")
    assert "- 10+ years Palantir: Not in locked job history." in text
    assert "- **10+ years Palantir:**" not in text


def test_job_id_txt_is_id_newline(tmp_path: Path):
    sandbox = _sandbox(tmp_path)
    upsert_job_description(sandbox, QUEUE_FIXTURE, job_id=JOB_ID)
    assert (sandbox / "job-id.txt").read_text(encoding="utf-8") == f"{JOB_ID}\n"


def test_job_id_mismatch_does_not_overwrite_jd(tmp_path: Path, capsys):
    sandbox = _sandbox(tmp_path)
    original = "ORIGINAL JD\n"
    (sandbox / "job-description.md").write_text(original, encoding="utf-8")
    (sandbox / "job-id.txt").write_text("other-id\n", encoding="utf-8")
    assert (
        main(
            [
                "--sandbox",
                str(sandbox),
                "--queue-file",
                str(QUEUE_FIXTURE),
                "--job-id",
                JOB_ID,
            ]
        )
        == 1
    )
    err = capsys.readouterr().err
    assert "job-id.txt mismatch" in err
    assert (sandbox / "job-description.md").read_text(encoding="utf-8") == original
    assert (sandbox / "job-id.txt").read_text(encoding="utf-8") == "other-id\n"


def test_same_job_id_overwrites_jd(tmp_path: Path):
    sandbox = _sandbox(tmp_path)
    (sandbox / "job-description.md").write_text("STALE JD\n", encoding="utf-8")
    (sandbox / "job-id.txt").write_text(f"{JOB_ID}\n", encoding="utf-8")
    dest = upsert_job_description(sandbox, QUEUE_FIXTURE, job_id=JOB_ID)
    text = dest.read_text(encoding="utf-8")
    assert "STALE JD" not in text
    assert "# LTS - Solution Architect" in text
    assert (sandbox / "job-id.txt").read_text(encoding="utf-8") == f"{JOB_ID}\n"


def test_mkdir_creates_missing_sandbox(tmp_path: Path):
    sandbox = tmp_path / "repo" / ".ai" / "history" / "resume-tailor" / "lts" / "solution-architect"
    assert not sandbox.exists()
    dest = upsert_job_description(sandbox, QUEUE_FIXTURE, job_id=JOB_ID)
    assert sandbox.is_dir()
    assert dest.is_file()
    assert (sandbox / "job-id.txt").is_file()


def test_empty_description_text_is_fail_closed(tmp_path: Path):
    sandbox = _sandbox(tmp_path)
    payload = _queue_copy()
    payload["jobs"][0]["description_text"] = "   "
    queue = _write_queue(tmp_path, payload)
    assert (
        main(
            [
                "--sandbox",
                str(sandbox),
                "--queue-file",
                str(queue),
                "--job-id",
                JOB_ID,
            ]
        )
        == 1
    )
    assert not (sandbox / "job-description.md").exists()


def test_missing_title_is_fail_closed(tmp_path: Path):
    sandbox = _sandbox(tmp_path)
    payload = _queue_copy()
    payload["jobs"][0]["title"] = ""
    queue = _write_queue(tmp_path, payload)
    assert (
        main(
            [
                "--sandbox",
                str(sandbox),
                "--queue-file",
                str(queue),
                "--job-id",
                JOB_ID,
            ]
        )
        == 1
    )
    assert not (sandbox / "job-description.md").exists()


def test_multi_job_queue_without_job_id_does_not_read_marker(tmp_path: Path):
    sandbox = _sandbox(tmp_path)
    (sandbox / "job-id.txt").write_text(f"{JOB_ID}\n", encoding="utf-8")
    payload = _queue_copy()
    extra = dict(payload["jobs"][0])
    extra["id"] = "greenhouse:lts:200"
    extra["title"] = "Enterprise Architect"
    payload["jobs"].append(extra)
    queue = _write_queue(tmp_path, payload)
    assert main(["--sandbox", str(sandbox), "--queue-file", str(queue)]) == 1
    assert not (sandbox / "job-description.md").exists()


def test_does_not_delete_queue_file(tmp_path: Path):
    sandbox = _sandbox(tmp_path)
    upsert_job_description(sandbox, QUEUE_FIXTURE, job_id=JOB_ID)
    assert QUEUE_FIXTURE.is_file()


def test_script_lives_on_allowlisted_path():
    assert (SCRIPTS_DIR / "upsert_job_description.py").is_file()
