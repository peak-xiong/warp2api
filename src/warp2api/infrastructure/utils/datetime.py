from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_iso(ts: Optional[str]) -> float:
    raw = (ts or "").strip()
    if not raw:
        return 0.0
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def future_iso(seconds: int) -> str:
    return datetime.fromtimestamp(
        datetime.now(timezone.utc).timestamp() + float(seconds), tz=timezone.utc
    ).isoformat()


def utcnow_timestamp() -> float:
    return datetime.now(timezone.utc).timestamp()
