"""generate-analysis-queue.py eligibility, slicing, and fail-closed queue checks."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch
import importlib.util
import sys

from conftest import SCRIPTS_DIR, make_job, write_day
from common.validate_analysis_request import validate_analysis_request


def _load_generator():
    spec = importlib.util.spec_from_file_location(
        "generate_analysis_queue",
        SCRIPTS_DIR / "generate-analysis-queue.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["generate_analysis_queue"] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _policy(max_jobs: int = 10) -> dict:
    return {
        "policies": [
            {
                "id": "job_analysis_policy_001",
                "execution": {
                    "default_mode": "sequential",
                    "max_jobs_per_agent": max_jobs,
                    "fresh_agent_per_batch": True,
                },
            }
        ],
    }


def _install_policy(root: Path, max_jobs: int = 10) -> None:
    (root / ".ai" / "guardrails" / "locked-agent-policies.json").write_text(
        json.dumps(_policy(max_jobs)), encoding="utf-8"
    )


def _write_stub(platform: Path, job_id: str, *, revision: int = 0) -> None:
    encoded = job_id.replace(":", "-")
    analyses = platform / "analyses"
    analyses.mkdir(parents=True, exist_ok=True)
    aid = 0 if revision == 0 else 1
    plat = job_id.split(":", 1)[0] if ":" in job_id else "greenhouse"
    doc = {
        "platform": plat,
        "job_id": job_id,
        "analysis_id": aid,
        "updated_at": "2026-08-11T16:00:00Z",
        "analyses": [
            {
                "analysis_id": aid,
                "job_id": job_id,
                "pull_date": "2026-08-11",
                "revision": revision,
                "is_current": True,
                "run_id": None if revision == 0 else "a" * 32,
                "analyzed_at": None if revision == 0 else "2026-08-11T17:00:00Z",
                "decision": None if revision == 0 else "approved",
                "justification": None if revision == 0 else "ok",
                "experience": {"requirements": []},
                "skills": {"requirements": []},
                "constraints": {"requirements": []},
                "external_context": {"decision_impact": "none", "sources": []},
            }
        ],
    }
    (analyses / f"{encoded}-analysis.json").write_text(json.dumps(doc), encoding="utf-8")


def _run_gen(root: Path, extra: list[str] | None = None) -> tuple[int, str]:
    gen = _load_generator()
    argv = ["--repo-root", str(root)]
    if extra:
        argv.extend(extra)
    with patch.object(gen, "utc_today") as today, patch.object(
        gen, "mint_run_id", side_effect=["a" * 32, "b" * 32, "c" * 32, "d" * 32, "e" * 32]
    ):
        today.return_value = __import__("datetime").date(2026, 8, 21)
        from io import StringIO

        buf = StringIO()
        err_buf = StringIO()
        old_out, old_err = sys.stdout, sys.stderr
        try:
            sys.stdout = buf
            sys.stderr = err_buf
            code = gen.main(argv)
        finally:
            sys.stdout = old_out
            sys.stderr = old_err
        return code, buf.getvalue() + err_buf.getvalue()


def _valid_job_row(job_id: str = "greenhouse:lts:100", status: str = "pending", **extra) -> dict:
    row = {
        "id": job_id,
        "status": status,
        "company": "LTS",
        "title": "Solution Architect",
        "location": "New York, NY",
        "work_location_type": "unknown",
        "url": "https://job-boards.greenhouse.io/lts/jobs/100",
        "description_text": "Architect role",
    }
    row.update(extra)
    return row


def test_golden_queue_file_validates(fixtures_dir):
    path = fixtures_dir / "queue" / "a1b2c3d4e5f6789012345678abcdef01-analysis-request.json"
    assert validate_analysis_request(path) == []


def test_leftover_schema_version_forbidden(fixtures_dir, tmp_path):
    src = fixtures_dir / "queue" / "a1b2c3d4e5f6789012345678abcdef01-analysis-request.json"
    doc = json.loads(src.read_text(encoding="utf-8"))
    doc["schema_version"] = "1.0"
    path = tmp_path / src.name
    path.write_text(json.dumps(doc), encoding="utf-8")
    errors = validate_analysis_request(path)
    assert any("schema_version" in e for e in errors)


def test_skip_reason_allowed_on_pending(tmp_path):
    path = tmp_path / "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-analysis-request.json"
    path.write_text(
        json.dumps(
            {
                "run_id": "a" * 32,
                "batch_number": 1,
                "platform": "greenhouse",
                "created_date": "2026-08-31",
                "invoke": "batch",
                "jobs": [
                    _valid_job_row(
                        job_id="greenhouse:lts:100",
                        status="pending",
                        skip_reason="sidecar missing",
                    )
                ],
            }
        ),
        encoding="utf-8",
    )
    assert validate_analysis_request(path) == []


def test_skip_reason_cleared_on_analysis_complete(tmp_path):
    path = tmp_path / "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-analysis-request.json"
    path.write_text(
        json.dumps(
            {
                "run_id": "a" * 32,
                "batch_number": 1,
                "platform": "greenhouse",
                "created_date": "2026-08-31",
                "invoke": "batch",
                "jobs": [
                    _valid_job_row(
                        job_id="greenhouse:lts:100",
                        status="analysis_complete",
                        skip_reason="sidecar missing",
                    )
                ],
            }
        ),
        encoding="utf-8",
    )
    errors = validate_analysis_request(path)
    assert any("skip_reason" in e for e in errors)


def test_nothing_eligible_writes_no_files(repo_layout):
    root = repo_layout["root"]
    _install_policy(root)
    code, out = _run_gen(root)
    assert code == 0
    assert "Nothing was eligible" in out
    queue = root / ".ai" / "history" / "job-search" / "queue"
    assert not list(queue.glob("*-analysis-request.json")) if queue.exists() else True


def test_fail_closed_when_queue_not_empty(repo_layout):
    root, src, platform = repo_layout["root"], repo_layout["src"], repo_layout["platform"]
    _install_policy(root)
    write_day(src, "2026-08-11", [make_job()])
    _write_stub(platform, "greenhouse:lts:100")
    queue = root / ".ai" / "history" / "job-search" / "queue"
    queue.mkdir(parents=True)
    leftover = queue / ("d" * 32 + "-analysis-request.json")
    leftover.write_text("{}", encoding="utf-8")
    code, out = _run_gen(root)
    assert code == 1
    assert "queue/ is not empty" in out


def test_no_arg_queues_revision_0_only(repo_layout):
    root, src, platform = repo_layout["root"], repo_layout["src"], repo_layout["platform"]
    _install_policy(root)
    write_day(
        src,
        "2026-08-11",
        [
            make_job(job_id="greenhouse:lts:100", source_job_id="100"),
            make_job(job_id="greenhouse:lts:200", source_job_id="200", title="Other"),
        ],
    )
    _write_stub(platform, "greenhouse:lts:100", revision=0)
    _write_stub(platform, "greenhouse:lts:200", revision=1)
    code, _ = _run_gen(root)
    assert code == 0
    files = list((root / ".ai" / "history" / "job-search" / "queue").glob("*-analysis-request.json"))
    assert len(files) == 1
    doc = json.loads(files[0].read_text(encoding="utf-8"))
    assert len(doc["jobs"]) == 1
    job_row = doc["jobs"][0]
    assert job_row["id"] == "greenhouse:lts:100"
    assert job_row["status"] == "pending"
    assert job_row["company"] == "LTS"
    assert job_row["title"] == "Solution Architect"
    assert job_row["location"] == "New York, NY"
    assert job_row["work_location_type"] == "unknown"
    assert job_row["url"] == "https://job-boards.greenhouse.io/lts/jobs/100"
    assert job_row["description_text"] == "Architect role"
    assert doc["run_id"] == "a" * 32
    assert doc["created_date"] == "2026-08-21"
    assert "schema_version" not in doc
    assert doc["invoke"] == "batch"
    assert validate_analysis_request(files[0]) == []


def test_job_id_queues_filled_ids(repo_layout):
    root, src, platform = repo_layout["root"], repo_layout["src"], repo_layout["platform"]
    _install_policy(root)
    write_day(src, "2026-08-11", [make_job(job_id="greenhouse:lts:200", source_job_id="200")])
    _write_stub(platform, "greenhouse:lts:200", revision=1)
    code, _ = _run_gen(root, ["--job-id", "greenhouse:lts:200"])
    assert code == 0
    files = list((root / ".ai" / "history" / "job-search" / "queue").glob("*-analysis-request.json"))
    assert len(files) == 1
    doc = json.loads(files[0].read_text(encoding="utf-8"))
    assert doc["jobs"][0]["id"] == "greenhouse:lts:200"
    assert doc["invoke"] == "batch"


def test_skip_closed_last_seen(repo_layout):
    root, src, platform = repo_layout["root"], repo_layout["src"], repo_layout["platform"]
    _install_policy(root)
    write_day(src, "2026-08-10", [make_job(status="closed")])
    _write_stub(platform, "greenhouse:lts:100")
    code, out = _run_gen(root, ["--job-id", "greenhouse:lts:100"])
    assert code == 0
    assert "every --job-id was skipped" in out.lower() or "SKIP greenhouse:lts:100" in out


def test_last_seen_not_latest_file_only(repo_layout):
    root, src, platform = repo_layout["root"], repo_layout["src"], repo_layout["platform"]
    _install_policy(root)
    write_day(src, "2026-08-10", [make_job(job_id="greenhouse:lts:100", source_job_id="100")])
    write_day(
        src,
        "2026-08-11",
        [make_job(job_id="greenhouse:lts:200", source_job_id="200", title="Other")],
    )
    _write_stub(platform, "greenhouse:lts:100")
    code, _ = _run_gen(root)
    assert code == 0
    files = list((root / ".ai" / "history" / "job-search" / "queue").glob("*-analysis-request.json"))
    doc = json.loads(files[0].read_text(encoding="utf-8"))
    assert [j["id"] for j in doc["jobs"]] == ["greenhouse:lts:100"]


def test_slice_by_max_jobs_per_agent(repo_layout):
    root, src, platform = repo_layout["root"], repo_layout["src"], repo_layout["platform"]
    _install_policy(root, max_jobs=1)
    jobs = [
        make_job(job_id=f"greenhouse:lts:{n}", source_job_id=str(n), title=f"Role {n}")
        for n in (100, 101)
    ]
    write_day(src, "2026-08-11", jobs)
    _write_stub(platform, "greenhouse:lts:100")
    _write_stub(platform, "greenhouse:lts:101")
    code, _ = _run_gen(root)
    assert code == 0
    files = sorted((root / ".ai" / "history" / "job-search" / "queue").glob("*-analysis-request.json"))
    assert len(files) == 2
    first = json.loads(files[0].read_text(encoding="utf-8"))
    second = json.loads(files[1].read_text(encoding="utf-8"))
    assert {first["batch_number"], second["batch_number"]} == {1, 2}
    assert all(len(doc["jobs"]) == 1 for doc in (first, second))


def test_skip_missing_sidecar(repo_layout):
    root, src = repo_layout["root"], repo_layout["src"]
    _install_policy(root)
    write_day(src, "2026-08-11", [make_job()])
    code, out = _run_gen(root, ["--job-id", "greenhouse:lts:100"])
    assert code == 0
    assert "no sidecar" in out


def test_default_invoke_is_batch(repo_layout):
    root, src, platform = repo_layout["root"], repo_layout["src"], repo_layout["platform"]
    _install_policy(root)
    write_day(src, "2026-08-11", [make_job()])
    _write_stub(platform, "greenhouse:lts:100")
    code, _ = _run_gen(root)
    assert code == 0
    files = list((root / ".ai" / "history" / "job-search" / "queue").glob("*-analysis-request.json"))
    doc = json.loads(files[0].read_text(encoding="utf-8"))
    assert doc["invoke"] == "batch"
    assert validate_analysis_request(files[0]) == []


def test_job_id_without_invoke_is_batch(repo_layout):
    root, src, platform = repo_layout["root"], repo_layout["src"], repo_layout["platform"]
    _install_policy(root)
    write_day(src, "2026-08-11", [make_job(job_id="greenhouse:lts:200", source_job_id="200")])
    _write_stub(platform, "greenhouse:lts:200", revision=1)
    code, _ = _run_gen(root, ["--job-id", "greenhouse:lts:200"])
    assert code == 0
    files = list((root / ".ai" / "history" / "job-search" / "queue").glob("*-analysis-request.json"))
    doc = json.loads(files[0].read_text(encoding="utf-8"))
    assert doc["invoke"] == "batch"


def test_invoke_manual_with_job_id(repo_layout):
    root, src, platform = repo_layout["root"], repo_layout["src"], repo_layout["platform"]
    _install_policy(root)
    write_day(src, "2026-08-11", [make_job(job_id="greenhouse:lts:200", source_job_id="200")])
    _write_stub(platform, "greenhouse:lts:200", revision=1)
    code, _ = _run_gen(root, ["--invoke", "manual", "--job-id", "greenhouse:lts:200"])
    assert code == 0
    files = list((root / ".ai" / "history" / "job-search" / "queue").glob("*-analysis-request.json"))
    doc = json.loads(files[0].read_text(encoding="utf-8"))
    assert doc["invoke"] == "manual"
    assert validate_analysis_request(files[0]) == []


def test_missing_invoke_fails_validator(tmp_path):
    path = tmp_path / "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-analysis-request.json"
    path.write_text(
        json.dumps(
            {
                "run_id": "a" * 32,
                "batch_number": 1,
                "platform": "greenhouse",
                "created_date": "2026-08-31",
                "jobs": [_valid_job_row("greenhouse:lts:100", "pending")],
            }
        ),
        encoding="utf-8",
    )
    errors = validate_analysis_request(path)
    assert any("invoke" in e for e in errors)


def _add_platform(root: Path, name: str) -> tuple[Path, Path]:
    platform = root / ".ai" / "history" / "job-search" / name
    src = platform / "src"
    src.mkdir(parents=True, exist_ok=True)
    return platform, src


def test_multi_platform_mints_separate_queue_files(repo_layout):
    root, src, platform = repo_layout["root"], repo_layout["src"], repo_layout["platform"]
    sap, sap_src = _add_platform(root, "serpapi")
    _install_policy(root)
    write_day(src, "2026-08-11", [make_job()])
    write_day(
        sap_src,
        "2026-08-11",
        [make_job(job_id="serpapi:indeed:100", source_job_id="100")],
        platform="serpapi",
    )
    _write_stub(platform, "greenhouse:lts:100")
    _write_stub(sap, "serpapi:indeed:100")
    code, _ = _run_gen(root)
    assert code == 0
    files = list((root / ".ai" / "history" / "job-search" / "queue").glob("*-analysis-request.json"))
    assert len(files) == 2
    docs = [json.loads(path.read_text(encoding="utf-8")) for path in files]
    by_platform = {doc["platform"]: doc for doc in docs}
    assert set(by_platform) == {"greenhouse", "serpapi"}
    assert [j["id"] for j in by_platform["greenhouse"]["jobs"]] == ["greenhouse:lts:100"]
    assert [j["id"] for j in by_platform["serpapi"]["jobs"]] == ["serpapi:indeed:100"]
    assert all(validate_analysis_request(path) == [] for path in files)


def test_platform_filter_serpapi_only(repo_layout):
    root, src, platform = repo_layout["root"], repo_layout["src"], repo_layout["platform"]
    sap, sap_src = _add_platform(root, "serpapi")
    _install_policy(root)
    write_day(src, "2026-08-11", [make_job()])
    write_day(
        sap_src,
        "2026-08-11",
        [make_job(job_id="serpapi:indeed:100", source_job_id="100")],
        platform="serpapi",
    )
    _write_stub(platform, "greenhouse:lts:100")
    _write_stub(sap, "serpapi:indeed:100")
    code, _ = _run_gen(root, ["--platform", "serpapi"])
    assert code == 0
    files = list((root / ".ai" / "history" / "job-search" / "queue").glob("*-analysis-request.json"))
    assert len(files) == 1
    doc = json.loads(files[0].read_text(encoding="utf-8"))
    assert doc["platform"] == "serpapi"
    assert [j["id"] for j in doc["jobs"]] == ["serpapi:indeed:100"]


def test_job_id_resolves_serpapi_prefix(repo_layout):
    root = repo_layout["root"]
    sap, sap_src = _add_platform(root, "serpapi")
    _install_policy(root)
    write_day(
        sap_src,
        "2026-08-11",
        [make_job(job_id="serpapi:indeed:200", source_job_id="200")],
        platform="serpapi",
    )
    _write_stub(sap, "serpapi:indeed:200", revision=1)
    code, _ = _run_gen(root, ["--job-id", "serpapi:indeed:200"])
    assert code == 0
    files = list((root / ".ai" / "history" / "job-search" / "queue").glob("*-analysis-request.json"))
    assert len(files) == 1
    doc = json.loads(files[0].read_text(encoding="utf-8"))
    assert doc["platform"] == "serpapi"
    assert doc["jobs"][0]["id"] == "serpapi:indeed:200"


def test_unknown_platform_flag_fail_closed(repo_layout):
    root = repo_layout["root"]
    _install_policy(root)
    code, out = _run_gen(root, ["--platform", "lever"])
    assert code == 1
    assert "not discovered" in out


def test_platform_comma_list_and_repeatable(repo_layout):
    root, src, platform = repo_layout["root"], repo_layout["src"], repo_layout["platform"]
    sap, sap_src = _add_platform(root, "serpapi")
    _install_policy(root)
    write_day(src, "2026-08-11", [make_job()])
    write_day(
        sap_src,
        "2026-08-11",
        [make_job(job_id="serpapi:indeed:100", source_job_id="100")],
        platform="serpapi",
    )
    _write_stub(platform, "greenhouse:lts:100")
    _write_stub(sap, "serpapi:indeed:100")
    code, _ = _run_gen(root, ["--platform", "serpapi,greenhouse"])
    assert code == 0
    files = list((root / ".ai" / "history" / "job-search" / "queue").glob("*-analysis-request.json"))
    assert {json.loads(p.read_text(encoding="utf-8"))["platform"] for p in files} == {
        "greenhouse",
        "serpapi",
    }


def test_skip_missing_or_blank_listing_fields(repo_layout):
    root, src, platform = repo_layout["root"], repo_layout["src"], repo_layout["platform"]
    _install_policy(root)
    write_day(
        src,
        "2026-08-11",
        [
            make_job(job_id="greenhouse:lts:100", source_job_id="100", description_text=""),
            make_job(job_id="greenhouse:lts:200", source_job_id="200", company="   "),
            make_job(job_id="greenhouse:lts:300", source_job_id="300"),
        ],
    )
    _write_stub(platform, "greenhouse:lts:100")
    _write_stub(platform, "greenhouse:lts:200")
    _write_stub(platform, "greenhouse:lts:300")
    code, out = _run_gen(root)
    assert code == 0
    assert "SKIP greenhouse:lts:100: missing or blank listing field(s): description_text" in out
    assert "SKIP greenhouse:lts:200: missing or blank listing field(s): company" in out
    files = list((root / ".ai" / "history" / "job-search" / "queue").glob("*-analysis-request.json"))
    assert len(files) == 1
    doc = json.loads(files[0].read_text(encoding="utf-8"))
    assert [j["id"] for j in doc["jobs"]] == ["greenhouse:lts:300"]


def test_skip_invalid_work_location_type(repo_layout):
    root, src, platform = repo_layout["root"], repo_layout["src"], repo_layout["platform"]
    _install_policy(root)
    write_day(
        src,
        "2026-08-11",
        [
            make_job(job_id="greenhouse:lts:100", source_job_id="100", work_location_type="invalid_type"),
            make_job(job_id="greenhouse:lts:200", source_job_id="200", work_location_type="remote"),
        ],
    )
    _write_stub(platform, "greenhouse:lts:100")
    _write_stub(platform, "greenhouse:lts:200")
    code, out = _run_gen(root)
    assert code == 0
    assert "SKIP greenhouse:lts:100: invalid work_location_type 'invalid_type'" in out
    files = list((root / ".ai" / "history" / "job-search" / "queue").glob("*-analysis-request.json"))
    assert len(files) == 1
    doc = json.loads(files[0].read_text(encoding="utf-8"))
    assert [j["id"] for j in doc["jobs"]] == ["greenhouse:lts:200"]
    assert doc["jobs"][0]["work_location_type"] == "remote"


def test_validator_listing_fields_and_enum_enforcement(tmp_path):
    path = tmp_path / "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-analysis-request.json"

    # Missing listing key
    bad_job = _valid_job_row()
    del bad_job["description_text"]
    path.write_text(
        json.dumps(
            {
                "run_id": "a" * 32,
                "batch_number": 1,
                "platform": "greenhouse",
                "created_date": "2026-08-31",
                "invoke": "batch",
                "jobs": [bad_job],
            }
        ),
        encoding="utf-8",
    )
    errors = validate_analysis_request(path)
    assert any("description_text: required non-empty string" in e for e in errors)

    # Blank listing key
    bad_job = _valid_job_row(company="  ")
    path.write_text(
        json.dumps(
            {
                "run_id": "a" * 32,
                "batch_number": 1,
                "platform": "greenhouse",
                "created_date": "2026-08-31",
                "invoke": "batch",
                "jobs": [bad_job],
            }
        ),
        encoding="utf-8",
    )
    errors = validate_analysis_request(path)
    assert any("company: required non-empty string" in e for e in errors)

    # Invalid work_location_type
    bad_job = _valid_job_row(work_location_type="telecommute")
    path.write_text(
        json.dumps(
            {
                "run_id": "a" * 32,
                "batch_number": 1,
                "platform": "greenhouse",
                "created_date": "2026-08-31",
                "invoke": "batch",
                "jobs": [bad_job],
            }
        ),
        encoding="utf-8",
    )
    errors = validate_analysis_request(path)
    assert any("work_location_type: required enum" in e for e in errors)

    # Unexpected key on row
    bad_job = _valid_job_row(decision="approved")
    path.write_text(
        json.dumps(
            {
                "run_id": "a" * 32,
                "batch_number": 1,
                "platform": "greenhouse",
                "created_date": "2026-08-31",
                "invoke": "batch",
                "jobs": [bad_job],
            }
        ),
        encoding="utf-8",
    )
    errors = validate_analysis_request(path)
    assert any("unexpected keys" in e for e in errors)
