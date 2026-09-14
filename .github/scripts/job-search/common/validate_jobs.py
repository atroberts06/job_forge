"""Fail-closed validation of a jobs.json pull file against the locked data model.

Jobs-only wrapper around validate_job_search.py. Does not require sidecars.
"""

from __future__ import annotations

import sys
from pathlib import Path

_JOB_SEARCH = Path(__file__).resolve().parents[1]
if str(_JOB_SEARCH) not in sys.path:
    sys.path.insert(0, str(_JOB_SEARCH))

from common.validate_job_search import is_utc_z, main as dispatcher_main, validate_file as _validate_file
from common.validate_job_search import validate_jobs_semantic as validate_semantic


def validate_file(jobs_path: Path, schema_path: Path) -> list[str]:
    """Validate jobs.json only (PULL_FILE). Sidecars are not required."""
    return _validate_file(jobs_path, schema_path, repo_root=None, require_stub=False)


def main(argv: list[str] | None = None) -> int:
    return dispatcher_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
