from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from warp2api.infrastructure.settings.settings import CLIENT_VERSION, OS_VERSION
from warp2api.infrastructure.auth.jwt_auth import refresh_jwt_token
from warp2api.observability.logging import logger

from warp2api.application.services.token_lock_service import token_lock
from warp2api.infrastructure.protobuf.minimal_request import build_minimal_warp_request
from warp2api.infrastructure.token_pool.repository import get_token_repository
from warp2api.infrastructure.transport.warp_transport import send_warp_protobuf_request

_QUOTA_COOLDOWN_SECONDS = int(os.getenv("WARP_TOKEN_COOLDOWN_SECONDS", "600"))
_COOLDOWN_SECONDS = int(os.getenv("WARP_TOKEN_ERROR_COOLDOWN_SECONDS", "180"))
_UNHEALTHY_FAILURE_THRESHOLD = int(os.getenv("WARP_TOKEN_UNHEALTHY_FAILURE_THRESHOLD", "3"))


def _should_rotate_token(result: Dict[str, Any]) -> bool:
    status = int(result.get("status_code") or 0)
    err = str(result.get("error") or "").lower()
    if status in (401, 403, 429):
        return True
    return (
        "no remaining quota" in err
        or "no ai requests remaining" in err
        or "invalid api key" in err
    )


def _is_quota_error(result: Dict[str, Any]) -> bool:
    status = int(result.get("status_code") or 0)
    err = str(result.get("error") or "").lower()
    return status == 429 or "no remaining quota" in err or "no ai requests remaining" in err


def _parse_iso(ts: Optional[str]) -> float:
    raw = (ts or "").strip()
    if not raw:
        return 0.0
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _future_iso(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def _status_from_result(result: Dict[str, Any]) -> str:
    status = int(result.get("status_code") or 0)
    err = str(result.get("error") or "").lower()

    if _is_quota_error(result):
        return "quota_exhausted"
    if status == 403:
        return "blocked"
    if status in (401, 429):
        return "cooldown"
    if status >= 500:
        return "cooldown"
    if "invalid_grant" in err:
        return "blocked"
    return "active"


def _select_pool_candidates(max_token_attempts: int) -> List[Dict[str, Any]]:
    repo = get_token_repository()
    now_ts = datetime.now(timezone.utc).timestamp()
    rows = repo.list_tokens()
    health_by_id = {int(h["token_id"]): h for h in repo.list_health_snapshots()}
    candidates: List[Dict[str, Any]] = []

    for row in rows:
        status = str(row.get("status") or "").strip()
        if status in {"disabled", "blocked", "quota_exhausted"}:
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
    candidates.sort(key=lambda x: (x["error_count"], x["use_count"], -x["last_success_ts"], x["id"]))
    if not candidates:
        return []

    state = repo.get_app_state("scheduler.last_token_id")
    last_id = int(state["value"]) if state and str(state.get("value", "")).isdigit() else None

    start = 0
    if last_id is not None:
        for idx, item in enumerate(candidates):
            if int(item["id"]) == last_id:
                start = (idx + 1) % len(candidates)
                break

    rotated = candidates[start:] + candidates[:start]
    return rotated[:max(1, max_token_attempts)]


def _apply_pool_result(token_id: int, result: Dict[str, Any]) -> None:
    repo = get_token_repository()
    now = _now_iso()
    token = repo.get_token(token_id)
    if not token:
        return

    curr_err = int(token.get("error_count") or 0)
    err_msg = str(result.get("error") or "")[:240]
    err_code = str(result.get("status_code") or "")
    status = _status_from_result(result)

    if result.get("ok"):
        repo.increment_use_count(token_id)
        repo.update_token(
            token_id,
            status="active",
            error_count=0,
            last_error_code="",
            last_error_message="",
            last_success_at=now,
            last_check_at=now,
            cooldown_until="",
        )
        repo.append_audit_log(
            action="runtime_send",
            actor="runtime",
            token_id=token_id,
            result="ok",
            detail=f"status={result.get('status_code')}",
        )
        return

    next_err = curr_err + 1
    cooldown_until = ""
    if status == "cooldown":
        cooldown_until = _future_iso(_COOLDOWN_SECONDS)
    if status == "quota_exhausted":
        cooldown_until = _future_iso(_QUOTA_COOLDOWN_SECONDS)

    repo.update_token(
        token_id,
        status=status,
        error_count=next_err,
        last_error_code=err_code,
        last_error_message=err_msg,
        last_check_at=now,
        cooldown_until=cooldown_until,
    )
    repo.append_audit_log(
        action="runtime_send",
        actor="runtime",
        token_id=token_id,
        result="failed",
        detail=f"status={result.get('status_code')} mapped_status={status} err={err_msg}",
    )


def _apply_pool_refresh_error(token_id: int, error: Exception) -> None:
    repo = get_token_repository()
    now = _now_iso()
    token = repo.get_token(token_id)
    if not token:
        return
    curr_err = int(token.get("error_count") or 0)
    msg = str(error)[:240]
    status = "blocked" if "invalid_grant" in msg.lower() else "cooldown"
    cooldown_until = "" if status == "blocked" else _future_iso(_COOLDOWN_SECONDS)
    repo.update_token(
        token_id,
        status=status,
        error_count=curr_err + 1,
        last_error_code="refresh_error",
        last_error_message=msg,
        last_check_at=now,
        cooldown_until=cooldown_until,
    )
    repo.append_audit_log(
        action="runtime_refresh",
        actor="runtime",
        token_id=token_id,
        result="failed",
        detail=f"mapped_status={status} err={msg}",
    )


def get_token_pool_status() -> Dict[str, Any]:
    repo = get_token_repository()
    items = repo.list_tokens()
    now_ts = datetime.now(timezone.utc).timestamp()

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
        "cooldown_seconds": _QUOTA_COOLDOWN_SECONDS,
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
    last_result: Dict[str, Any] = {"ok": False, "status_code": 503, "error": "no token attempted"}
    candidates = _select_pool_candidates(max_token_attempts=max_token_attempts)

    if not candidates:
        return {
            "ok": False,
            "status_code": 503,
            "error": "token pool is empty or no active token available",
            "attempts": attempts,
            "model_tag": model_tag,
        }

    for candidate in candidates:
        token_id = int(candidate["id"])
        refresh_token = candidate["refresh_token"]
        repo = get_token_repository()
        repo.set_app_state("scheduler.last_token_id", str(token_id))

        try:
            async with token_lock(token_id):
                token_data = await refresh_jwt_token(refresh_token_override=refresh_token)
                jwt = str(token_data.get("access_token") or token_data.get("id_token") or "").strip()
                if not jwt:
                    raise RuntimeError("refresh returned empty token")

                result = send_warp_protobuf_request(
                    body=protobuf_bytes,
                    jwt=jwt,
                    timeout_seconds=timeout_seconds,
                    client_version=client_version or CLIENT_VERSION,
                    os_version=os_version or OS_VERSION,
                )
                _apply_pool_result(token_id, result)
                attempts.append(
                    {
                        "mode": "token_pool",
                        "token_id": token_id,
                        "status_code": result.get("status_code"),
                        "error": str(result.get("error") or "")[:200],
                    }
                )
                last_result = result

                if result.get("ok") or not _should_rotate_token(result):
                    result["attempts"] = attempts
                    if model_tag is not None:
                        result["model_tag"] = model_tag
                    return result
        except Exception as exc:
            _apply_pool_refresh_error(token_id, exc)
            attempts.append(
                {
                    "mode": "token_pool",
                    "token_id": token_id,
                    "status_code": 0,
                    "error": str(exc)[:200],
                }
            )
            last_result = {"ok": False, "status_code": 502, "error": str(exc)}
            logger.warning("token pool rotation attempt failed: token_id=%s err=%s", token_id, exc)

    last_result["attempts"] = attempts
    if model_tag is not None:
        last_result["model_tag"] = model_tag
    return last_result
