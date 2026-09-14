"""Truncate, append, and rewrite telemetry trailer on .ai/history/orchestrator/run.log."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_JOB_SEARCH = Path(__file__).resolve().parents[1]
if str(_JOB_SEARCH) not in sys.path:
    sys.path.insert(0, str(_JOB_SEARCH))

from common.validate_job_search import repo_root_from_here

LOG_REL = Path(".ai") / "history" / "orchestrator" / "run.log"
TRAILER_DELIMITER = "--- orch-telemetry ---"
TELEMETRY_KEYS = (
    "started_at",
    "ended_at",
    "tokens_in",
    "tokens_out",
    "cache_tokens_in",
    "thinking_tokens",
    "context_usage_percent",
    "context_metric_status",
)
STATUS_ENUM = ("not_programmatically_available", "observed")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log_path(root: Path) -> Path:
    return root / LOG_REL


def split_log(text: str) -> tuple[str, str | None]:
    """Split chat body from a trailing telemetry block. Trailer includes the delimiter through EOF."""
    if not text:
        return text, None
    found = -1
    start = 0
    while True:
        idx = text.find(TRAILER_DELIMITER, start)
        if idx == -1:
            break
        at_line = idx == 0 or text[idx - 1] == "\n"
        end = idx + len(TRAILER_DELIMITER)
        after_ok = end == len(text) or text[end] in "\n"
        if at_line and after_ok:
            found = idx
        start = idx + 1
    if found == -1:
        return text, None
    return text[:found], text[found:]


def format_trailer(payload: dict[str, Any]) -> str:
    ordered = {key: payload[key] for key in TELEMETRY_KEYS}
    return f"{TRAILER_DELIMITER}\n{json.dumps(ordered, ensure_ascii=False)}\n"


def normalize_telemetry(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("telemetry must be a JSON object")
    extra = set(raw) - set(TELEMETRY_KEYS)
    missing = set(TELEMETRY_KEYS) - set(raw)
    if extra or missing:
        raise ValueError(f"telemetry keys extra={sorted(extra)} missing={sorted(missing)}")
    status = raw["context_metric_status"]
    if status not in STATUS_ENUM:
        raise ValueError("context_metric_status must be not_programmatically_available or observed")
    return {key: raw[key] for key in TELEMETRY_KEYS}


def truncate(root: Path) -> Path:
    path = log_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    return path


def _stamp_block(text: str, stamp: str) -> str:
    body = text if text.endswith("\n") or text == "" else f"{text}\n"
    lines = body.splitlines() or [""]
    return "\n" + "".join(f"{stamp} {line}\n" for line in lines)


def append(root: Path, text: str, *, now: str | None = None) -> Path:
    path = log_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = now or utc_now()
    block = _stamp_block(text, stamp)
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    body, trailer = split_log(existing)
    if trailer is None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(block)
        return path
    path.write_text(body + block + trailer, encoding="utf-8")
    return path


def write_telemetry(root: Path, payload: dict[str, Any]) -> Path:
    path = log_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    body, _ = split_log(existing)
    path.write_text(body + format_trailer(payload), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Truncate, append, or rewrite orchestrator run.log telemetry")
    parser.add_argument("--truncate", action="store_true")
    parser.add_argument("--append", default=None, help="Chat-visible text to append")
    parser.add_argument(
        "--telemetry",
        default=None,
        help="JSON object replacing the run.log telemetry trailer (same closed keys as sidecar analyses[])",
    )
    parser.add_argument("--repo-root", default=None)
    args = parser.parse_args(argv)
    chosen = sum(1 for flag in (args.truncate, args.append is not None, args.telemetry is not None) if flag)
    if chosen != 1:
        print("ERROR: pass exactly one of --truncate, --append, or --telemetry", file=sys.stderr)
        return 1
    root = Path(args.repo_root).resolve() if args.repo_root else repo_root_from_here()
    if args.truncate:
        path = truncate(root)
        print(f"Truncated {path}")
        return 0
    if args.telemetry is not None:
        try:
            payload = normalize_telemetry(json.loads(args.telemetry))
        except (json.JSONDecodeError, ValueError) as exc:
            print(f"ERROR: telemetry: {exc}", file=sys.stderr)
            return 1
        path = write_telemetry(root, payload)
        print(f"Telemetry {path}")
        return 0
    path = append(root, args.append or "")
    print(f"Appended {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
