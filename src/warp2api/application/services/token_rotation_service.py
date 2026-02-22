from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from warp2api.infrastructure.utils.datetime import parse_iso, utcnow_timestamp
from warp2api.infrastructure.settings.settings import (
    CLIENT_VERSION,
    OS_VERSION,
    WARP_REQUEST_RETRY_BASE_DELAY_MS,
    WARP_REQUEST_RETRY_COUNT,
    WARP_TOKEN_COOLDOWN_SECONDS,
    WARP_TOKEN_UNHEALTHY_FAILURE_THRESHOLD,
)
from warp2api.infrastructure.auth.jwt_auth import refresh_jwt_token
from warp2api.observability.logging import logger

from warp2api.application.services.token_lock_service import token_lock
from warp2api.application.services.token_pool_service import get_token_pool_service
from warp2api.domain.protocols.token_repository import TokenRepositoryProtocol
from warp2api.infrastructure.protobuf.minimal_request import build_minimal_warp_request
from warp2api.infrastructure.token_pool.repository import get_token_repository
from warp2api.infrastructure.transport.warp_transport import send_warp_protobuf_request

_UNHEALTHY_FAILURE_THRESHOLD = WARP_TOKEN_UNHEALTHY_FAILURE_THRESHOLD
_REQUEST_RETRY_COUNT = WARP_REQUEST_RETRY_COUNT
_REQUEST_RETRY_BASE_DELAY_MS = WARP_REQUEST_RETRY_BASE_DELAY_MS

_parse_iso = parse_iso


def _is_retryable_result(result: Dict[str, Any]) -> bool:
    if result.get("ok"):
        return False
    status = int(result.get("status_code") or 0)
    err = str(result.get("error") or "").lower()
    if status in {0, 408, 425, 429, 500, 502, 503, 504}:
        return True
    retry_markers = (
        "failed to fetch",
        "timeout",
        "timed out",
        "temporarily unavailable",
        "connection refused",
        "connection reset",
        "something went wrong with this conversation",
    )
    return any(m in err for m in retry_markers)


def _is_model_not_allowed_error(result: Dict[str, Any]) -> bool:
    err = str(result.get("error") or "").lower()
    return (
        "requested base model" in err and "is not allowed for your account" in err
    ) or ("model" in err and "not allowed for your account" in err)


def _should_rotate_token(result: Dict[str, Any]) -> bool:
    status = int(result.get("status_code") or 0)
    err = str(result.get("error") or "").lower()
    if status in (0, 401, 403, 429) or status >= 500:
        return True
    if _is_model_not_allowed_error(result):
        return True
    return (
        "no remaining quota" in err
        or "no ai requests remaining" in err
        or "invalid api key" in err
        or "failed to fetch" in err
        or "timed out" in err
        or "timeout" in err
        or "connection refused" in err
        or "connection reset" in err
        or "something went wrong with this conversation" in err
    )


def _select_pool_candidates(max_token_attempts: int) -> List[Dict[str, Any]]:
    repo: TokenRepositoryProtocol = get_token_repository()
    now_ts = utcnow_timestamp()
    rows = repo.list_tokens()
    health_by_id = {
        int(h["token_id"]): h for h in repo.list_health_snapshots()}
    candidates: List[Dict[str, Any]] = []

    for row in rows:
        status = str(row.get("status") or "").strip()
        # Strict routing: only active tokens are eligible for model traffic.
        if status != "active":
            continue

        cooldown_until = str(row.get("cooldown_until") or "").strip()
        if cooldown_until and _parse_iso(cooldown_until) > now_ts:
            continue

        token_id = int(row["id"])
        health = health_by_id.get(token_id) or {}
        healthy = bool(health.get("healthy", True))
        failures = int(health.get("consecutive_failures") or 0)
        if (not healthy) and failures >= _UNHEALTHY_FAILURE_THRESHOLD:
            continue

        refresh_token = repo.get_refresh_token(token_id)
        if not refresh_token:
            continue

        candidates.append(
            {
                "id": token_id,
                "refresh_token": refresh_token,
                "error_count": int(row.get("error_count") or 0),
                "last_success_ts": _parse_iso(row.get("last_success_at")),
                "use_count": int(row.get("use_count") or 0),
            }
        )

    # Smart-even scheduling:
    # 1) hard availability filter done above
    # 2) quality ranking (error/use/last_success)
    # 3) round-robin over the ranked list to avoid hotspot accounts
    candidates.sort(key=lambda x: (
        x["error_count"], x["use_count"], -x["last_success_ts"], x["id"]))
    if not candidates:
        return []

    state = repo.get_app_state("scheduler.last_token_id")
    last_id = int(state["value"]) if state and str(
        state.get("value", "")).isdigit() else None

    start = 0
    if last_id is not None:
        for idx, item in enumerate(candidates):
            if int(item["id"]) == last_id:
                start = (idx + 1) % len(candidates)
                break

    rotated = candidates[start:] + candidates[:start]
    return rotated[:max(1, max_token_attempts)]


def get_token_pool_status() -> Dict[str, Any]:
    repo = get_token_repository()
    items = repo.list_tokens()
    now_ts = utcnow_timestamp()

    out = []
    for item in items:
        cu = str(item.get("cooldown_until") or "").strip()
        remain = max(0, int(_parse_iso(cu) - now_ts)) if cu else 0
        out.append(
            {
                "id": item.get("id"),
                "warp_refresh_token": item.get("warp_refresh_token"),
                "status": item.get("status"),
                "error_count": item.get("error_count"),
                "in_cooldown": remain > 0,
                "cooldown_remaining_seconds": remain,
            }
        )

    return {
        "token_count": len(out),
        "cooldown_seconds": WARP_TOKEN_COOLDOWN_SECONDS,
        "tokens": out,
        "by_status": repo.statistics().get("by_status", {}),
    }


async def send_query_with_rotation(
    query: str,
    model_tag: str,
    timeout_seconds: int = 90,
    client_version: Optional[str] = None,
    os_version: Optional[str] = None,
    max_token_attempts: int = 4,
) -> Dict[str, Any]:
    body = build_minimal_warp_request(query=query, model_tag=model_tag)
    return await send_protobuf_with_rotation(
        protobuf_bytes=body,
        timeout_seconds=timeout_seconds,
        client_version=client_version,
        os_version=os_version,
        max_token_attempts=max_token_attempts,
        model_tag=model_tag,
    )


async def send_protobuf_with_rotation(
    protobuf_bytes: bytes,
    timeout_seconds: int = 90,
    client_version: Optional[str] = None,
    os_version: Optional[str] = None,
    max_token_attempts: int = 4,
    model_tag: Optional[str] = None,
) -> Dict[str, Any]:
    attempts: List[Dict[str, Any]] = []
    last_result: Dict[str, Any] = {
        "ok": False, "status_code": 503, "error": "no token attempted"}
    candidates = _select_pool_candidates(max_token_attempts=max_token_attempts)

    if not candidates:
        repo = get_token_repository()
        total_tokens = int((repo.statistics() or {}).get("total", 0) or 0)
        if total_tokens == 0:
            err = "token pool has no token account configured, please import accounts in /admin/tokens"
        else:
            err = "token pool has no active token available, please check token status in /admin/tokens"
        return {
            "ok": False,
            "status_code": 503,
            "error": err,
            "attempts": attempts,
            "model_tag": model_tag,
        }

    for candidate in candidates:
        pool = get_token_pool_service()
        token_id = int(candidate["id"])
        refresh_token = candidate["refresh_token"]
        repo = get_token_repository()
        repo.set_app_state("scheduler.last_token_id", str(token_id))

        try:
            async with token_lock(token_id):
                token_data = await refresh_jwt_token(refresh_token_override=refresh_token)
                jwt = str(token_data.get("access_token")
                          or token_data.get("id_token") or "").strip()
                if not jwt:
                    raise RuntimeError("refresh returned empty token")

                final_result: Dict[str, Any] = {
                    "ok": False, "status_code": 502, "error": "request not executed"}
                for req_try in range(1, _REQUEST_RETRY_COUNT + 1):
                    try:
                        result = await send_warp_protobuf_request(
                            body=protobuf_bytes,
                            jwt=jwt,
                            timeout_seconds=timeout_seconds,
                            client_version=client_version or CLIENT_VERSION,
                            os_version=os_version or OS_VERSION,
                        )
                    except Exception as exc:
                        result = {"ok": False,
                                  "status_code": 0, "error": str(exc)}

                    final_result = result
                    err_info = pool.parse_runtime_request_error(result)
                    attempts.append(
                        {
                            "mode": "token_pool",
                            "token_id": token_id,
                            "try": req_try,
                            "status_code": result.get("status_code"),
                            "error_code": err_info["code"],
                            "error": err_info["message"][:200],
                        }
                    )
                    last_result = result

                    if result.get("ok"):
                        break
                    if req_try >= _REQUEST_RETRY_COUNT or not _is_retryable_result(result):
                        break

                    delay_s = (_REQUEST_RETRY_BASE_DELAY_MS * req_try) / 1000.0
                    if delay_s > 0:
                        await asyncio.sleep(delay_s)

                pool.mark_runtime_request_result(
                    token_id, final_result, actor="runtime")
                if final_result.get("ok") or not _should_rotate_token(final_result):
                    final_result["attempts"] = attempts
                    if model_tag is not None:
                        final_result["model_tag"] = model_tag
                    return final_result
        except Exception as exc:
            pool.mark_runtime_refresh_error(token_id, exc, actor="runtime")
            attempts.append(
                {
                    "mode": "token_pool",
                    "token_id": token_id,
                    "status_code": 0,
                    "error": str(exc)[:200],
                }
            )
            last_result = {"ok": False, "status_code": 502, "error": str(exc)}
            logger.warning(
                "token pool rotation attempt failed: token_id=%s err=%s", token_id, exc)

    last_result["attempts"] = attempts
    if model_tag is not None:
        last_result["model_tag"] = model_tag
    return last_result
