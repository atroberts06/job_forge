"""purge_dated_src.py in-scope vs out-of-scope dates."""

from __future__ import annotations

from datetime import date
from io import StringIO
from unittest.mock import patch

import common.purge_dated_src as purge


def _run(root, today: date) -> tuple[int, str]:
    buf = StringIO()
    with patch.object(purge, "utc_today", return_value=today):
        old_out, old_err = __import__("sys").stdout, __import__("sys").stderr
        try:
            __import__("sys").stdout = buf
            __import__("sys").stderr = buf
            code = purge.main(["--repo-root", str(root)])
        finally:
            __import__("sys").stdout = old_out
            __import__("sys").stderr = old_err
    return code, buf.getvalue()


def test_purges_only_dated_src_older_than_30_utc_days(repo_layout):
    root = repo_layout["root"]
    platform = repo_layout["platform"]
    src = repo_layout["src"]
    old = src / "2026-07-30"
    edge = src / "2026-07-31"
    recent = src / "2026-08-15"
    for folder in (old, edge, recent):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "jobs.json").write_text("{}", encoding="utf-8")
    analyses = platform / "analyses"
    analyses.mkdir(parents=True, exist_ok=True)
    keep_sidecar = analyses / "keep-analysis.json"
    keep_sidecar.write_text("{}", encoding="utf-8")
    ledger = platform / "approved-jobs.json"
    ledger.write_text("{}", encoding="utf-8")
    queue = root / ".ai" / "history" / "job-search" / "queue"
    queue.mkdir(parents=True, exist_ok=True)
    queue_file = queue / "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-analysis-request.json"
    queue_file.write_text("{}", encoding="utf-8")
    dashboard = root / ".ai" / "history" / "job-search" / "dashboard"
    dashboard.mkdir(parents=True, exist_ok=True)
    dash_file = dashboard / "index.html"
    dash_file.write_text("<html></html>", encoding="utf-8")

    code, out = _run(root, date(2026, 8, 30))
    assert code == 0
    assert "Purged folders: 1" in out
    assert not old.exists()
    assert edge.is_dir()
    assert recent.is_dir()
    assert keep_sidecar.is_file()
    assert ledger.is_file()
    assert queue_file.is_file()
    assert dash_file.is_file()


def test_does_not_purge_non_dated_src_children(repo_layout):
    root = repo_layout["root"]
    leftover = repo_layout["src"] / "rebuild-manifest.json"
    leftover.write_text("{}", encoding="utf-8")
    code, out = _run(root, date(2026, 8, 30))
    assert code == 0
    assert leftover.is_file()
    assert "Purged folders: 0" in out
