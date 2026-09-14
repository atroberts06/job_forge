"""UTC clock helpers shared by pull and stub writers."""

from __future__ import annotations

from datetime import datetime, timezone


def now_iso() -> str:
    """UTC timestamp with Z suffix (sole time standard)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
