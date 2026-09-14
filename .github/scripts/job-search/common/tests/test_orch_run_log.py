"""orch_run_log.py truncate, timestamped append, and replaceable telemetry trailer."""

from __future__ import annotations

import json
from pathlib import Path

import common.orch_run_log as log

TELEMETRY_A = {
    "started_at": "2026-08-31T12:00:00Z",
    "ended_at": None,
    "tokens_in": None,
    "tokens_out": None,
    "cache_tokens_in": None,
    "thinking_tokens": None,
    "context_usage_percent": None,
    "context_metric_status": "not_programmatically_available",
}
TELEMETRY_B = {
    **TELEMETRY_A,
    "tokens_in": 10,
    "tokens_out": 20,
    "context_metric_status": "observed",
}


def test_truncate_then_append(tmp_path: Path):
    root = tmp_path / "repo"
    path = log.truncate(root)
    assert path.read_text(encoding="utf-8") == ""
    log.append(root, "first line\nsecond", now="2026-08-31T12:00:00Z")
    text = path.read_text(encoding="utf-8")
    assert text == (
        "\n"
        "2026-08-31T12:00:00Z first line\n"
        "2026-08-31T12:00:00Z second\n"
    )
    log.append(root, "third", now="2026-08-31T12:00:01Z")
    text = path.read_text(encoding="utf-8")
    assert text == (
        "\n"
        "2026-08-31T12:00:00Z first line\n"
        "2026-08-31T12:00:00Z second\n"
        "\n"
        "2026-08-31T12:00:01Z third\n"
    )
    log.truncate(root)
    assert path.read_text(encoding="utf-8") == ""


def test_append_preserves_existing_trailer(tmp_path: Path):
    root = tmp_path / "repo"
    path = log.truncate(root)
    log.write_telemetry(root, TELEMETRY_A)
    log.append(root, "first", now="2026-08-31T12:00:00Z")
    text = path.read_text(encoding="utf-8")
    body, trailer = log.split_log(text)
    assert "2026-08-31T12:00:00Z first" in body
    assert trailer is not None
    assert trailer.count(log.TRAILER_DELIMITER) == 1
    payload = json.loads(trailer.split("\n", 1)[1])
    assert payload["started_at"] == TELEMETRY_A["started_at"]
    log.append(root, "second", now="2026-08-31T12:00:01Z")
    text = path.read_text(encoding="utf-8")
    assert text.count(log.TRAILER_DELIMITER) == 1
    assert "2026-08-31T12:00:01Z second" in text
    assert text.index("first") < text.index(log.TRAILER_DELIMITER)


def test_replace_trailer_twice_without_duplicating(tmp_path: Path):
    root = tmp_path / "repo"
    path = log.truncate(root)
    log.write_telemetry(root, TELEMETRY_A)
    log.write_telemetry(root, TELEMETRY_B)
    text = path.read_text(encoding="utf-8")
    assert text.count(log.TRAILER_DELIMITER) == 1
    _, trailer = log.split_log(text)
    assert trailer is not None
    payload = json.loads(trailer.split("\n", 1)[1])
    assert payload["tokens_in"] == 10
    assert payload["tokens_out"] == 20
    log.append(root, "chat", now="2026-08-31T12:05:00Z")
    ended = {**TELEMETRY_B, "ended_at": "2026-08-31T12:10:00Z"}
    log.write_telemetry(root, ended)
    text = path.read_text(encoding="utf-8")
    assert text.count(log.TRAILER_DELIMITER) == 1
    body, trailer = log.split_log(text)
    assert "2026-08-31T12:05:00Z chat" in body
    payload = json.loads(trailer.split("\n", 1)[1])
    assert payload["ended_at"] == "2026-08-31T12:10:00Z"


def test_cli_requires_exactly_one_action(tmp_path: Path):
    assert log.main(["--repo-root", str(tmp_path)]) == 1
    assert log.main(["--repo-root", str(tmp_path), "--truncate", "--append", "x"]) == 1
    assert log.main(["--repo-root", str(tmp_path), "--truncate", "--telemetry", "{}"]) == 1
    assert log.main(["--repo-root", str(tmp_path / "repo"), "--truncate"]) == 0
    payload = json.dumps(TELEMETRY_A)
    assert log.main(["--repo-root", str(tmp_path / "repo"), "--telemetry", payload]) == 0
    path = log.log_path(tmp_path / "repo")
    assert log.TRAILER_DELIMITER in path.read_text(encoding="utf-8")
