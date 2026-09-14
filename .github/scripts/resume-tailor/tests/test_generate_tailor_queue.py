"""generate-tailor-queue.py mint, skip, and P2-J1 payload tests."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from conftest import SCRIPTS_DIR
from validate_tailor_request import validate_tailor_request

JOB_ID = "greenhouse:lts:100"
JOB_ID_2 = "greenhouse:lts:200"
SKILL = {
    "jd_excerpt": "Salesforce platform experience",
    "normalized": "Salesforce",
    "source_section": "Requirements",
    "importance": "preferred",
    "result": "met",
    "evidence": "Salesforce Education Cloud in selected skills.",
    "note": "Named platform evidenced in locked-skills.json.",
}
CORE_THEMES = {
    "job_skill_1": "Salesforce Education Cloud",
    "job_skill_2": "Systems Integration",
    "job_skill_3": "Cloud Strategy",
    "strength_1": "Enterprise Architecture Governance",
    "strength_2": "Cross-functional Team Leadership",
    "strength_3": "End-to-End Migration Execution",
    "opening_hook": (
        "I bring deep enterprise integration and Salesforce architecture "
        "leadership to modernize scalable institutional systems at LTS."
    ),
}


def _load_generator():
    spec = importlib.util.spec_from_file_location(
        "generate_tailor_queue",
        SCRIPTS_DIR / "generate-tailor-queue.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["generate_tailor_queue"] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _install_policy(root: Path, max_jobs: int = 10) -> None:
    (root / ".ai" / "guardrails" / "locked-agent-policies.json").write_text(
        json.dumps(
            {
                "policies": [
                    {
                        "id": "resume_tailor_policy_001",
                        "execution": {
                            "default_mode": "sequential",
                            "max_jobs_per_agent": max_jobs,
                            "fresh_agent_per_batch": True,
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def _write_jobs(
    src: Path,
    job_id: str,
    *,
    source_job_id: str | None = "100",
    platform: str = "greenhouse",
    title: str = "Solution Architect",
    company: str = "LTS",
) -> None:
    day = src / "2026-08-11"
    day.mkdir(parents=True, exist_ok=True)
    existing = {"platform": platform, "pulled_at": "2026-08-11T12:00:00Z", "jobs": []}
    path = day / "jobs.json"
    if path.is_file():
        existing = json.loads(path.read_text(encoding="utf-8"))
    job: dict = {
        "id": job_id,
        "status": "new",
        "title": title,
        "company": company,
        "location": "New York, NY",
        "work_location_type": "unknown",
        "url": f"https://job-boards.greenhouse.io/lts/jobs/{source_job_id or 'missing'}",
        "pulled_at": "2026-08-11",
        "status_updated_at": "2026-08-11T15:00:00Z",
        "description_text": "Architect Salesforce and CI/CD.",
    }
    if source_job_id is not None:
        job["source_job_id"] = source_job_id
    existing["jobs"].append(job)
    path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")


def _write_sidecar(
    platform: Path,
    job_id: str,
    skills: list[dict] | None = None,
    core_themes: dict | None = None,
) -> None:
    analyses = platform / "analyses"
    analyses.mkdir(parents=True, exist_ok=True)
    plat = job_id.split(":", 1)[0] if ":" in job_id else "greenhouse"
    doc = {
        "platform": plat,
        "job_id": job_id,
        "analysis_id": 1,
        "updated_at": "2026-08-30T12:00:00Z",
        "analyses": [
            {
                "analysis_id": 1,
                "job_id": job_id,
                "pull_date": "2026-08-11",
                "revision": 1,
                "is_current": True,
                "run_id": "a" * 32,
                "analyzed_at": "2026-08-30T12:00:00Z",
                "decision": "approved",
                "justification": "Locked skills evidence Salesforce.",
                "experience": {"requirements": []},
                "skills": {"requirements": skills if skills is not None else [SKILL]},
                "constraints": {"requirements": []},
                "external_context": {"decision_impact": "none", "sources": []},
            }
        ],
    }
    if core_themes is not None:
        doc["analyses"][0]["core_themes"] = core_themes
    (analyses / f"{job_id.replace(':', '-')}-analysis.json").write_text(
        json.dumps(doc), encoding="utf-8"
    )


def _write_ledger(platform: Path, jobs: list[dict], *, plat: str | None = None) -> None:
    name = plat or (jobs[0]["id"].split(":", 1)[0] if jobs and ":" in str(jobs[0].get("id") or "") else "greenhouse")
    (platform / "approved-jobs.json").write_text(
        json.dumps({"platform": name, "jobs": jobs}, indent=2)
        + "\n",
        encoding="utf-8",
    )


def _approved(job_id: str, **extra) -> dict:
    row = {
        "id": job_id,
        "analysis_id": 1,
        "approved_at": "2026-08-30T12:00:00Z",
        "status": "approved",
        "status_updated_at": "2026-08-30T12:00:00Z",
        "started_at": None,
        "attempt_count": None,
        "completed_at": None,
        "pr_url": None,
        "pr_number": None,
        "sandbox_path": None,
        "feature_branch": None,
    }
    row.update(extra)
    return row


def _run(root: Path, extra: list[str] | None = None) -> tuple[int, str]:
    gen = _load_generator()
    argv = ["--repo-root", str(root)]
    if extra:
        argv.extend(extra)
    buf = StringIO()
    with patch.object(gen, "utc_today", return_value=date(2026, 8, 30)), patch.object(
        gen, "mint_run_id", side_effect=["c" * 32, "d" * 32]
    ):
        old_out, old_err = sys.stdout, sys.stderr
        try:
            sys.stdout = buf
            sys.stderr = buf
            code = gen.main(argv)
        finally:
            sys.stdout = old_out
            sys.stderr = old_err
    return code, buf.getvalue()


def test_golden_queue_file_validates(fixtures_dir):
    path = fixtures_dir / "queue" / "c1d2e3f4a5b6789012345678abcdef01-tailor-request.json"
    assert validate_tailor_request(path) == []


def test_leftover_schema_version_forbidden(fixtures_dir, tmp_path):
    src = fixtures_dir / "queue" / "c1d2e3f4a5b6789012345678abcdef01-tailor-request.json"
    doc = json.loads(src.read_text(encoding="utf-8"))
    doc["schema_version"] = "1.0"
    path = tmp_path / src.name
    path.write_text(json.dumps(doc), encoding="utf-8")
    errors = validate_tailor_request(path)
    assert any("schema_version" in e for e in errors)


def test_nothing_eligible_writes_no_files(repo_layout):
    root = repo_layout["root"]
    _install_policy(root)
    _write_ledger(repo_layout["platform"], [])
    code, out = _run(root)
    assert code == 0
    assert "Nothing was eligible" in out
    queue = root / ".ai" / "history" / "resume-tailor" / "queue"
    assert list(queue.glob("*-tailor-request.json")) == []


def test_mints_approved_only_with_mentioned_skills(repo_layout):
    root = repo_layout["root"]
    platform = repo_layout["platform"]
    _install_policy(root)
    _write_jobs(repo_layout["src"], JOB_ID)
    _write_jobs(repo_layout["src"], JOB_ID_2, source_job_id="200")
    _write_sidecar(platform, JOB_ID)
    _write_sidecar(platform, JOB_ID_2)
    _write_ledger(
        platform,
        [
            _approved(JOB_ID),
            {
                "id": JOB_ID_2,
                "analysis_id": 1,
                "approved_at": "2026-08-30T12:00:00Z",
                "status": "in_progress",
            },
            {
                "id": "greenhouse:lts:300",
                "analysis_id": 1,
                "approved_at": "2026-08-30T12:00:00Z",
                "status": "completed",
            },
            {
                "id": "greenhouse:lts:400",
                "analysis_id": 1,
                "approved_at": "2026-08-30T12:00:00Z",
                "status": "failed",
            },
            {
                "id": "greenhouse:lts:500",
                "analysis_id": 1,
                "approved_at": "2026-08-30T12:00:00Z",
                "status": "deployed",
            },
        ],
    )
    code, _ = _run(root)
    assert code == 0
    files = list((root / ".ai" / "history" / "resume-tailor" / "queue").glob("*-tailor-request.json"))
    assert len(files) == 1
    assert files[0].name == f"{'c' * 32}-tailor-request.json"
    doc = json.loads(files[0].read_text(encoding="utf-8"))
    assert doc["run_id"] == "c" * 32
    assert doc["batch_number"] == 1
    assert "schema_version" not in doc
    assert "mode" not in doc
    assert "pull_date" not in doc
    assert [row["id"] for row in doc["jobs"]] == [JOB_ID]
    row = doc["jobs"][0]
    assert row["status"] == "pending"
    assert row["company"] == "LTS"
    assert row["title"] == "Solution Architect"
    assert row["decision"] == "approved"
    assert row["mentioned_skills"] == [SKILL]
    assert row["company_slug"] == "lts"
    assert row["position_slug"] == "solution-architect-100"
    assert row["started_at"] is None
    assert row["completed_at"] is None
    assert row["attempt_count"] is None
    assert row["pr_url"] is None
    assert row["pr_number"] is None
    assert row["sandbox_path"] is None
    assert row["feature_branch"] is None
    assert "core_themes" not in row
    assert validate_tailor_request(files[0]) == []


def test_job_id_filter_mints_one_approved_row(repo_layout):
    root = repo_layout["root"]
    platform = repo_layout["platform"]
    _install_policy(root)
    _write_jobs(repo_layout["src"], JOB_ID)
    _write_jobs(repo_layout["src"], JOB_ID_2, source_job_id="200")
    _write_sidecar(platform, JOB_ID)
    _write_sidecar(platform, JOB_ID_2)
    _write_ledger(platform, [_approved(JOB_ID), _approved(JOB_ID_2)])
    code, _ = _run(root, ["--job-id", JOB_ID_2])
    assert code == 0
    files = list((root / ".ai" / "history" / "resume-tailor" / "queue").glob("*-tailor-request.json"))
    assert len(files) == 1
    doc = json.loads(files[0].read_text(encoding="utf-8"))
    assert [row["id"] for row in doc["jobs"]] == [JOB_ID_2]
    assert doc["jobs"][0]["company_slug"] == "lts"
    assert doc["jobs"][0]["position_slug"] == "solution-architect-200"


def test_slices_by_max_jobs_per_agent(repo_layout):
    root = repo_layout["root"]
    platform = repo_layout["platform"]
    _install_policy(root, max_jobs=1)
    _write_jobs(repo_layout["src"], JOB_ID)
    _write_jobs(repo_layout["src"], JOB_ID_2, source_job_id="200")
    _write_sidecar(platform, JOB_ID)
    _write_sidecar(platform, JOB_ID_2)
    _write_ledger(platform, [_approved(JOB_ID), _approved(JOB_ID_2)])
    code, _ = _run(root)
    assert code == 0
    files = sorted((root / ".ai" / "history" / "resume-tailor" / "queue").glob("*-tailor-request.json"))
    assert [p.name for p in files] == [f"{'c' * 32}-tailor-request.json", f"{'d' * 32}-tailor-request.json"]
    first = json.loads(files[0].read_text(encoding="utf-8"))
    second = json.loads(files[1].read_text(encoding="utf-8"))
    assert first["batch_number"] == 1
    assert second["batch_number"] == 2


def test_leftover_queue_fail_closed(repo_layout):
    root = repo_layout["root"]
    _install_policy(root)
    queue = root / ".ai" / "history" / "resume-tailor" / "queue"
    queue.mkdir(parents=True)
    leftover = queue / f"{'e' * 32}-tailor-request.json"
    leftover.write_text("{}", encoding="utf-8")
    code, out = _run(root)
    assert code == 1
    assert "not empty" in out


def _add_platform(root: Path, name: str) -> tuple[Path, Path]:
    platform = root / ".ai" / "history" / "job-search" / name
    src = platform / "src"
    src.mkdir(parents=True, exist_ok=True)
    return platform, src


def test_multi_platform_mints_separate_queue_files(repo_layout):
    root = repo_layout["root"]
    gh = repo_layout["platform"]
    sap, sap_src = _add_platform(root, "serpapi")
    _install_policy(root)
    _write_jobs(repo_layout["src"], JOB_ID)
    _write_jobs(sap_src, "serpapi:indeed:100", platform="serpapi")
    _write_sidecar(gh, JOB_ID)
    _write_sidecar(sap, "serpapi:indeed:100")
    _write_ledger(gh, [_approved(JOB_ID)])
    _write_ledger(sap, [_approved("serpapi:indeed:100")], plat="serpapi")
    code, _ = _run(root)
    assert code == 0
    files = list((root / ".ai" / "history" / "resume-tailor" / "queue").glob("*-tailor-request.json"))
    assert len(files) == 2
    docs = [json.loads(path.read_text(encoding="utf-8")) for path in files]
    by_platform = {doc["platform"]: doc for doc in docs}
    assert set(by_platform) == {"greenhouse", "serpapi"}
    assert [row["id"] for row in by_platform["greenhouse"]["jobs"]] == [JOB_ID]
    assert [row["id"] for row in by_platform["serpapi"]["jobs"]] == ["serpapi:indeed:100"]
    assert all(validate_tailor_request(path) == [] for path in files)


def test_platform_filter_serpapi_only(repo_layout):
    root = repo_layout["root"]
    gh = repo_layout["platform"]
    sap, sap_src = _add_platform(root, "serpapi")
    _install_policy(root)
    _write_jobs(repo_layout["src"], JOB_ID)
    _write_jobs(sap_src, "serpapi:indeed:100", platform="serpapi")
    _write_sidecar(gh, JOB_ID)
    _write_sidecar(sap, "serpapi:indeed:100")
    _write_ledger(gh, [_approved(JOB_ID)])
    _write_ledger(sap, [_approved("serpapi:indeed:100")], plat="serpapi")
    code, _ = _run(root, ["--platform", "serpapi"])
    assert code == 0
    files = list((root / ".ai" / "history" / "resume-tailor" / "queue").glob("*-tailor-request.json"))
    assert len(files) == 1
    doc = json.loads(files[0].read_text(encoding="utf-8"))
    assert doc["platform"] == "serpapi"
    assert [row["id"] for row in doc["jobs"]] == ["serpapi:indeed:100"]


def test_job_id_resolves_serpapi_prefix(repo_layout):
    root = repo_layout["root"]
    sap, sap_src = _add_platform(root, "serpapi")
    _install_policy(root)
    _write_jobs(sap_src, "serpapi:indeed:200", source_job_id="200", platform="serpapi")
    _write_sidecar(sap, "serpapi:indeed:200")
    _write_ledger(sap, [_approved("serpapi:indeed:200")], plat="serpapi")
    code, _ = _run(root, ["--job-id", "serpapi:indeed:200"])
    assert code == 0
    files = list((root / ".ai" / "history" / "resume-tailor" / "queue").glob("*-tailor-request.json"))
    assert len(files) == 1
    doc = json.loads(files[0].read_text(encoding="utf-8"))
    assert doc["platform"] == "serpapi"
    assert [row["id"] for row in doc["jobs"]] == ["serpapi:indeed:200"]
    assert doc["jobs"][0]["position_slug"] == "solution-architect-200"


def test_source_job_id_longer_than_ten_uses_last_ten(repo_layout):
    root = repo_layout["root"]
    platform = repo_layout["platform"]
    job_id = "greenhouse:lts:99173226320"
    _install_policy(root)
    _write_jobs(repo_layout["src"], job_id, source_job_id="99173226320", title="Lead Data Engineer")
    _write_sidecar(platform, job_id)
    _write_ledger(platform, [_approved(job_id)])
    code, _ = _run(root)
    assert code == 0
    files = list((root / ".ai" / "history" / "resume-tailor" / "queue").glob("*-tailor-request.json"))
    doc = json.loads(files[0].read_text(encoding="utf-8"))
    row = doc["jobs"][0]
    assert row["company_slug"] == "lts"
    assert row["position_slug"] == "lead-data-engineer-9173226320"
    assert validate_tailor_request(files[0]) == []


def test_same_title_different_source_job_id_unique_slugs(repo_layout):
    root = repo_layout["root"]
    platform = repo_layout["platform"]
    first = "greenhouse:lts:98149423888"
    second = "greenhouse:lts:99173226320"
    _install_policy(root)
    _write_jobs(
        repo_layout["src"],
        first,
        source_job_id="98149423888",
        title="Lead Data Engineer",
    )
    _write_jobs(
        repo_layout["src"],
        second,
        source_job_id="99173226320",
        title="Lead Data Engineer",
    )
    _write_sidecar(platform, first)
    _write_sidecar(platform, second)
    _write_ledger(platform, [_approved(first), _approved(second)])
    code, _ = _run(root)
    assert code == 0
    files = list((root / ".ai" / "history" / "resume-tailor" / "queue").glob("*-tailor-request.json"))
    doc = json.loads(files[0].read_text(encoding="utf-8"))
    slugs = [row["position_slug"] for row in doc["jobs"]]
    assert slugs == [
        "lead-data-engineer-8149423888",
        "lead-data-engineer-9173226320",
    ]
    assert slugs[0] != slugs[1]


def test_missing_source_job_id_fail_closed(repo_layout):
    root = repo_layout["root"]
    platform = repo_layout["platform"]
    _install_policy(root)
    _write_jobs(repo_layout["src"], JOB_ID, source_job_id=None)
    _write_sidecar(platform, JOB_ID)
    _write_ledger(platform, [_approved(JOB_ID)])
    code, out = _run(root)
    assert code == 1
    assert "cannot mint slugs" in out
    queue = root / ".ai" / "history" / "resume-tailor" / "queue"
    assert list(queue.glob("*-tailor-request.json")) == []


def test_validator_requires_kebab_slugs(fixtures_dir, tmp_path):
    src = fixtures_dir / "queue" / "c1d2e3f4a5b6789012345678abcdef01-tailor-request.json"
    doc = json.loads(src.read_text(encoding="utf-8"))
    del doc["jobs"][0]["company_slug"]
    del doc["jobs"][0]["position_slug"]
    path = tmp_path / src.name
    path.write_text(json.dumps(doc), encoding="utf-8")
    errors = validate_tailor_request(path)
    assert any("company_slug: required" in e for e in errors)
    assert any("position_slug: required" in e for e in errors)


def test_copies_resume_keys_and_nulls_timestamps(repo_layout):
    root = repo_layout["root"]
    platform = repo_layout["platform"]
    _install_policy(root)
    _write_jobs(repo_layout["src"], JOB_ID)
    _write_sidecar(platform, JOB_ID)
    _write_ledger(
        platform,
        [
            _approved(
                JOB_ID,
                started_at="2026-08-29T12:00:00Z",
                attempt_count=2,
                completed_at="2026-08-29T13:00:00Z",
                pr_url="https://github.com/example/job-forge/pull/99",
                pr_number=99,
                sandbox_path=".ai/history/resume-tailor/lts/solution-architect/",
                feature_branch="feature/lts-solution-architect",
            )
        ],
    )
    code, _ = _run(root)
    assert code == 0
    files = list((root / ".ai" / "history" / "resume-tailor" / "queue").glob("*-tailor-request.json"))
    assert len(files) == 1
    row = json.loads(files[0].read_text(encoding="utf-8"))["jobs"][0]
    assert row["started_at"] is None
    assert row["completed_at"] is None
    assert row["attempt_count"] == 2
    assert row["pr_url"] == "https://github.com/example/job-forge/pull/99"
    assert row["pr_number"] == 99
    assert row["sandbox_path"] == ".ai/history/resume-tailor/lts/solution-architect/"
    assert row["feature_branch"] == "feature/lts-solution-architect"
    assert validate_tailor_request(files[0]) == []


def test_copies_core_themes_when_sidecar_has_them(repo_layout):
    root = repo_layout["root"]
    platform = repo_layout["platform"]
    _install_policy(root)
    _write_jobs(repo_layout["src"], JOB_ID)
    _write_sidecar(platform, JOB_ID, core_themes=CORE_THEMES)
    _write_ledger(platform, [_approved(JOB_ID)])
    code, _ = _run(root)
    assert code == 0
    files = list((root / ".ai" / "history" / "resume-tailor" / "queue").glob("*-tailor-request.json"))
    row = json.loads(files[0].read_text(encoding="utf-8"))["jobs"][0]
    assert row["core_themes"] == CORE_THEMES
    assert validate_tailor_request(files[0]) == []


def test_validator_rejects_incomplete_core_themes(fixtures_dir, tmp_path):
    src = fixtures_dir / "queue" / "c1d2e3f4a5b6789012345678abcdef01-tailor-request.json"
    doc = json.loads(src.read_text(encoding="utf-8"))
    doc["jobs"][0]["core_themes"] = {"job_skill_1": "Salesforce Education Cloud"}
    path = tmp_path / src.name
    path.write_text(json.dumps(doc), encoding="utf-8")
    errors = validate_tailor_request(path)
    assert any("core_themes: missing keys" in e for e in errors)


def test_validator_rejects_extra_core_theme_keys(fixtures_dir, tmp_path):
    src = fixtures_dir / "queue" / "c1d2e3f4a5b6789012345678abcdef01-tailor-request.json"
    doc = json.loads(src.read_text(encoding="utf-8"))
    extra = dict(CORE_THEMES)
    extra["job_skill_4"] = "Invented Skill"
    doc["jobs"][0]["core_themes"] = extra
    path = tmp_path / src.name
    path.write_text(json.dumps(doc), encoding="utf-8")
    errors = validate_tailor_request(path)
    assert any("unexpected keys" in e for e in errors)
