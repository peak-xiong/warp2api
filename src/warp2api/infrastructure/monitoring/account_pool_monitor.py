#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Background account-pool monitor.

Periodically validates refresh tokens by attempting JWT refresh and stores
health snapshots for API diagnostics.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import time
from dataclasses import dataclass, asdict
from typing import Dict, Optional

from warp2api.infrastructure.auth.jwt_auth import get_refresh_token_candidates, refresh_jwt_token
from warp2api.observability.logging import logger


@dataclass
class TokenHealth:
    token_preview: str
    token_id: str
    healthy: bool = False
    last_checked_at: float = 0.0
    last_success_at: float = 0.0
    last_error: str = ""
    consecutive_failures: int = 0
    latency_ms: int = 0


_MONITOR_TASK: Optional[asyncio.Task] = None
_STOP_EVENT: Optional[asyncio.Event] = None
_HEALTH: Dict[str, TokenHealth] = {}


def _monitor_interval_seconds() -> int:
    raw = os.getenv("WARP_POOL_HEALTH_INTERVAL_SECONDS", "120")
    try:
        return max(15, int(raw))
    except Exception:
        return 120


def _token_preview(token: str) -> str:
    if not token:
        return ""
    if len(token) <= 10:
        return token[:2] + "***"
    return f"{token[:6]}...{token[-4:]}"


def _token_id(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


async def _check_one_token(token: str) -> None:
    token_key = _token_id(token)
    item = _HEALTH.get(token_key) or TokenHealth(token_preview=_token_preview(token), token_id=token_key)
    start = time.monotonic()

    try:
        data = await refresh_jwt_token(refresh_token_override=token)
        elapsed = int((time.monotonic() - start) * 1000)
        access = str((data or {}).get("access_token") or (data or {}).get("id_token") or "").strip()
        if not access:
            raise RuntimeError("refresh returned empty access token")

        item.healthy = True
        item.last_checked_at = time.time()
        item.last_success_at = item.last_checked_at
        item.last_error = ""
        item.consecutive_failures = 0
        item.latency_ms = elapsed
    except Exception as exc:
        elapsed = int((time.monotonic() - start) * 1000)
        item.healthy = False
        item.last_checked_at = time.time()
        item.last_error = str(exc)[:240]
        item.consecutive_failures += 1
        item.latency_ms = elapsed

    _HEALTH[token_key] = item


async def _run_monitor(stop_event: asyncio.Event) -> None:
    interval = _monitor_interval_seconds()
    logger.info("[token_pool] monitor started, interval=%ss", interval)

    while not stop_event.is_set():
        try:
            tokens = get_refresh_token_candidates()
            if tokens:
                await asyncio.gather(*(_check_one_token(t) for t in tokens))
            else:
                logger.warning("[token_pool] no refresh tokens found for health check")
        except Exception as exc:
            logger.warning("[token_pool] monitor cycle failed: %s", exc)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass

    logger.info("[token_pool] monitor stopped")


async def start_monitor() -> None:
    global _MONITOR_TASK, _STOP_EVENT
    if _MONITOR_TASK and not _MONITOR_TASK.done():
        return

    _STOP_EVENT = asyncio.Event()
    _MONITOR_TASK = asyncio.create_task(_run_monitor(_STOP_EVENT), name="warp-token-pool-monitor")


async def stop_monitor() -> None:
    global _MONITOR_TASK, _STOP_EVENT
    if not _MONITOR_TASK:
        return

    if _STOP_EVENT:
        _STOP_EVENT.set()

    try:
        await _MONITOR_TASK
    except Exception:
        pass

    _MONITOR_TASK = None
    _STOP_EVENT = None


def get_monitor_status() -> Dict[str, object]:
    task_running = bool(_MONITOR_TASK and not _MONITOR_TASK.done())
    items = [asdict(v) for v in _HEALTH.values()]
    items.sort(key=lambda x: x.get("token_preview", ""))

    healthy = sum(1 for x in items if x.get("healthy"))
    unhealthy = len(items) - healthy

    return {
        "running": task_running,
        "interval_seconds": _monitor_interval_seconds(),
        "token_count": len(items),
        "healthy_count": healthy,
        "unhealthy_count": unhealthy,
        "items": items,
    }
