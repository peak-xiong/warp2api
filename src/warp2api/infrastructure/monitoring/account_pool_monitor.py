#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Background account-pool monitor.

Periodically validates refresh tokens by attempting JWT refresh and stores
health snapshots for API diagnostics.
"""

from __future__ import annotations

import asyncio
import time
from typing import Dict, Optional

from warp2api.application.services.token_pool_service import get_token_pool_service
from warp2api.infrastructure.settings.settings import (
    WARP_POOL_MONITOR_INTERVAL_SECONDS,
    WARP_POOL_MONITOR_MAX_PARALLEL,
    WARP_POOL_QUOTA_RETRY_LEAD_SECONDS,
    WARP_POOL_TOKEN_REFRESH_INTERVAL_SECONDS,
)
from warp2api.infrastructure.token_pool.repository import get_token_repository
from warp2api.observability.logging import logger


_MONITOR_TASK: Optional[asyncio.Task] = None
_STOP_EVENT: Optional[asyncio.Event] = None


def _monitor_interval_seconds() -> int:
    return WARP_POOL_MONITOR_INTERVAL_SECONDS


def _per_token_refresh_interval_seconds() -> int:
    return WARP_POOL_TOKEN_REFRESH_INTERVAL_SECONDS


def _max_parallel_checks() -> int:
    return WARP_POOL_MONITOR_MAX_PARALLEL


def _quota_retry_lead_seconds() -> int:
    return WARP_POOL_QUOTA_RETRY_LEAD_SECONDS


def _parse_ts(raw: object) -> float:
    if raw is None:
        return 0.0
    if isinstance(raw, (int, float)):
        v = float(raw)
        if v > 1e12:
            return v / 1000.0
        return v
    s = str(raw).strip()
    if not s:
        return 0.0
    try:
        if s.replace(".", "", 1).isdigit():
            v = float(s)
            if v > 1e12:
                return v / 1000.0
            return v
        from datetime import datetime

        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


async def _check_one_token(token_id: int) -> None:
    repo = get_token_repository()
    prev = repo.get_health_snapshot(token_id) or {}
    start = time.monotonic()

    try:
        svc = get_token_pool_service()
        result = await svc.health_check_token(token_id, actor="monitor")
        elapsed = int((time.monotonic() - start) * 1000)
        ok = bool((result or {}).get("success"))
        if not ok:
            raise RuntimeError("token health check failed")

        now_ts = time.time()
        repo.upsert_health_snapshot(
            token_id=token_id,
            healthy=True,
            last_checked_at=now_ts,
            last_success_at=now_ts,
            last_error="",
            consecutive_failures=0,
            latency_ms=elapsed,
        )
    except Exception as exc:
        elapsed = int((time.monotonic() - start) * 1000)
        now_ts = time.time()
        last_success_at = float(prev.get("last_success_at") or 0.0)
        consecutive_failures = int(prev.get("consecutive_failures") or 0) + 1
        repo.upsert_health_snapshot(
            token_id=token_id,
            healthy=False,
            last_checked_at=now_ts,
            last_success_at=last_success_at,
            last_error=str(exc)[:240],
            consecutive_failures=consecutive_failures,
            latency_ms=elapsed,
        )


async def _run_monitor(stop_event: asyncio.Event) -> None:
    interval = _monitor_interval_seconds()
    per_token_interval = _per_token_refresh_interval_seconds()
    max_parallel = _max_parallel_checks()
    quota_lead = _quota_retry_lead_seconds()
    logger.info(
        "[token_pool] monitor started, tick=%ss per_token=%ss parallel=%s quota_lead=%ss",
        interval,
        per_token_interval,
        max_parallel,
        quota_lead,
    )

    while not stop_event.is_set():
        try:
            svc = get_token_pool_service()
            tokens = svc.list_tokens()
            if tokens:
                now_ts = time.time()
                due_ids = []
                for t in tokens:
                    status = str(t.get("status") or "")
                    if status not in {"active", "cooldown", "quota_exhausted"}:
                        continue

                    if status == "quota_exhausted":
                        next_refresh_ts = _parse_ts(t.get("quota_next_refresh_time"))
                        if next_refresh_ts > 0 and (next_refresh_ts - now_ts) > quota_lead:
                            continue

                    last_check_ts = _parse_ts(t.get("last_check_at")) or _parse_ts(t.get("health_last_checked_at"))
                    if last_check_ts > 0 and (now_ts - last_check_ts) < per_token_interval:
                        continue
                    due_ids.append(int(t["id"]))

                if due_ids:
                    sem = asyncio.Semaphore(max_parallel)

                    async def _guarded_check(token_id: int) -> None:
                        async with sem:
                            await _check_one_token(token_id)

                    await asyncio.gather(*(_guarded_check(tid) for tid in due_ids))
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
    except asyncio.CancelledError:
        # Graceful shutdown during server stop/reload.
        pass
    except Exception:
        pass

    _MONITOR_TASK = None
    _STOP_EVENT = None


def get_monitor_status() -> Dict[str, object]:
    repo = get_token_repository()
    task_running = bool(_MONITOR_TASK and not _MONITOR_TASK.done())
    items = repo.list_health_snapshots()
    items.sort(key=lambda x: int(x.get("token_id") or 0))

    healthy = sum(1 for x in items if bool(x.get("healthy")))
    unhealthy = len(items) - healthy

    return {
        "running": task_running,
        "interval_seconds": _monitor_interval_seconds(),
        "per_token_refresh_interval_seconds": _per_token_refresh_interval_seconds(),
        "max_parallel_checks": _max_parallel_checks(),
        "quota_retry_lead_seconds": _quota_retry_lead_seconds(),
        "token_count": len(items),
        "healthy_count": healthy,
        "unhealthy_count": unhealthy,
        "items": items,
    }
