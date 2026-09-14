"""Delete dated job-search src folders older than UTC today minus 30 days (ADR-027)."""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

_JOB_SEARCH = Path(__file__).resolve().parents[1]
if str(_JOB_SEARCH) not in sys.path:
    sys.path.insert(0, str(_JOB_SEARCH))

from common.validate_job_search import repo_root_from_here

RETENTION_DAYS = 30
_DATE_FMT = "%Y-%m-%d"


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


def cutoff_date(today: date) -> date:
    return today - timedelta(days=RETENTION_DAYS)


def dated_src_dirs(platform_root: Path) -> list[Path]:
    src = platform_root / "src"
    if not src.is_dir():
        return []
    found: list[Path] = []
    for child in src.iterdir():
        if not child.is_dir():
            continue
        try:
            datetime.strptime(child.name, _DATE_FMT)
        except ValueError:
            continue
        found.append(child)
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Purge dated src/ folders older than 30 UTC days")
    parser.add_argument("--repo-root", default=None)
    args = parser.parse_args(argv)

    root = Path(args.repo_root).resolve() if args.repo_root else repo_root_from_here()
    job_search = root / ".ai" / "history" / "job-search"
    if not job_search.is_dir():
        print("No job-search history directory.")
        return 0

    today = utc_today()
    cutoff = cutoff_date(today)
    removed = 0
    for platform_root in sorted(p for p in job_search.iterdir() if p.is_dir()):
        if platform_root.name in {"queue", "dashboard"}:
            continue
        for folder in dated_src_dirs(platform_root):
            folder_date = datetime.strptime(folder.name, _DATE_FMT).date()
            if folder_date < cutoff:
                shutil.rmtree(folder)
                print(f"Purged {folder.relative_to(root)}")
                removed += 1
    print(f"Purged folders: {removed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
