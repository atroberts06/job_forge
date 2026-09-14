#!/usr/bin/env python3
"""Stamp approved-jobs.json deployed + artifacts_url after Drive sync.

CD deploy is the only writer of these two fields. Empty folder mappings are a
no-op (orch ledger-only / empty-manifest runs must not stamp deployed).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_CI_DIR = Path(__file__).resolve().parent
_JOB_SEARCH = Path(__file__).resolve().parents[2] / ".github" / "scripts" / "job-search"

_ci_common_spec = importlib.util.spec_from_file_location("ci_common", _CI_DIR / "common.py")
assert _ci_common_spec is not None and _ci_common_spec.loader is not None
_ci_common = importlib.util.module_from_spec(_ci_common_spec)
_ci_common_spec.loader.exec_module(_ci_common)
resume_tailor_identity = _ci_common.resume_tailor_identity

if str(_JOB_SEARCH) not in sys.path:
    sys.path.insert(0, str(_JOB_SEARCH))

from common.validate_job_search import load_json, validate_file  # noqa: E402

STAMPABLE = "completed"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_sandbox(path: str) -> str:
    return str(path or "").replace("\\", "/").rstrip("/")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def ledger_files(root: Path) -> list[Path]:
    base = root / ".ai" / "history" / "job-search"
    if not base.is_dir():
        return []
    return sorted(base.glob("*/approved-jobs.json"))


def load_sync_folders(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    folders = doc.get("folders") if isinstance(doc, dict) else None
    if not isinstance(folders, list):
        return []
    return [row for row in folders if isinstance(row, dict)]


def stamp_row(row: dict[str, Any], artifacts_url: str, now: str) -> bool:
    if row.get("status") != STAMPABLE:
        return False
    row["status"] = "deployed"
    row["artifacts_url"] = artifacts_url
    row["status_updated_at"] = now
    return True


def apply_folders(root: Path, folders: list[dict[str, Any]], now: str) -> int:
    by_sandbox: dict[str, str] = {}
    for folder in folders:
        sandbox = normalize_sandbox(str(folder.get("resume_tailor_directory") or ""))
        url = str(folder.get("artifacts_url") or "").strip()
        if sandbox and url:
            by_sandbox[sandbox] = url
    if not by_sandbox:
        print("No Drive folder mappings — skipping deployed stamp.")
        return 0

    stamped = 0
    schema = root / ".ai" / "guardrails" / "locked-job-search-data-model.json"
    for path in ledger_files(root):
        ledger = load_json(path)
        jobs = ledger.get("jobs")
        if not isinstance(jobs, list):
            continue
        mutated = False
        for row in jobs:
            if not isinstance(row, dict):
                continue
            sandbox = normalize_sandbox(str(row.get("sandbox_path") or ""))
            url = by_sandbox.get(sandbox)
            if not url:
                continue
            if stamp_row(row, url, now):
                mutated = True
                stamped += 1
        if mutated:
            write_json(path, ledger)
            errors = validate_file(path, schema, repo_root=root)
            if errors:
                print(f"ERROR: ledger validator failed for {path}:", file=sys.stderr)
                for err in errors:
                    print(f"  - {err}", file=sys.stderr)
                return 1
    print(f"Stamped deployed on {stamped} ledger row(s).")
    return 0


def lookup_job_id(root: Path, job_id: str, now: str) -> int:
    target_path = None
    ledger = None
    target = None
    for path in ledger_files(root):
        doc = load_json(path)
        for row in doc.get("jobs") or []:
            if isinstance(row, dict) and row.get("id") == job_id:
                target_path = path
                ledger = doc
                target = row
                break
        if target is not None:
            break
    if target is None or target_path is None or ledger is None:
        print(f"ERROR: ledger row missing for {job_id}", file=sys.stderr)
        return 1
    sandbox = normalize_sandbox(str(target.get("sandbox_path") or ""))
    if not sandbox:
        print(f"ERROR: {job_id} has no sandbox_path", file=sys.stderr)
        return 1
    company, role = resume_tailor_identity(Path(sandbox))
    root_folder_id = os.environ.get("GDRIVE_FOLDER_ID")
    if not root_folder_id:
        print("ERROR: GDRIVE_FOLDER_ID is not set.", file=sys.stderr)
        return 1
    from sync_gdrive import find_folder, folder_url, get_drive_service

    service = get_drive_service()
    company_id = find_folder(service, company, root_folder_id)
    if not company_id:
        print(f"ERROR: Drive folder not found for company {company!r}", file=sys.stderr)
        return 1
    role_id = find_folder(service, role, company_id)
    if not role_id:
        print(f"ERROR: Drive folder not found for {company}/{role}", file=sys.stderr)
        return 1
    url = folder_url(role_id)
    if not stamp_row(target, url, now):
        print(
            f"ERROR: {job_id} status is {target.get('status')!r}; only {STAMPABLE} can be stamped.",
            file=sys.stderr,
        )
        return 1
    write_json(target_path, ledger)
    schema = root / ".ai" / "guardrails" / "locked-job-search-data-model.json"
    errors = validate_file(target_path, schema, repo_root=root)
    if errors:
        print(f"ERROR: ledger validator failed for {target_path}:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    print(f"Stamped deployed on {job_id} artifacts_url={url}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stamp ledger deployed after Drive sync")
    parser.add_argument("--from-sync", default="dist/drive-sync-result.json")
    parser.add_argument("--lookup-job-id", default=None)
    parser.add_argument("--repo-root", default=None)
    args = parser.parse_args(argv)
    root = Path(args.repo_root).resolve() if args.repo_root else Path.cwd()
    now = utc_now()
    if args.lookup_job_id:
        return lookup_job_id(root, args.lookup_job_id, now)
    sync_path = Path(args.from_sync)
    if not sync_path.is_absolute():
        sync_path = (root / sync_path).resolve()
    return apply_folders(root, load_sync_folders(sync_path), now)


if __name__ == "__main__":
    raise SystemExit(main())
