from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional

from warp2api.infrastructure.settings.settings import CLIENT_VERSION, OS_VERSION
from warp2api.infrastructure.auth.jwt_auth import get_refresh_token_candidates, get_valid_jwt, refresh_jwt_token
from warp2api.observability.logging import logger

from warp2api.infrastructure.protobuf.minimal_request import build_minimal_warp_request
from warp2api.infrastructure.transport.warp_transport import send_warp_protobuf_request

_REFRESH_TOKEN_COOLDOWN_UNTIL: Dict[str, float] = {}
_QUOTA_COOLDOWN_SECONDS = int(os.getenv("WARP_TOKEN_COOLDOWN_SECONDS", "600"))


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


def _cooldown_active(refresh_token: str) -> bool:
    until = _REFRESH_TOKEN_COOLDOWN_UNTIL.get(refresh_token, 0.0)
    return until > time.time()


def _mark_cooldown(refresh_token: str) -> None:
    _REFRESH_TOKEN_COOLDOWN_UNTIL[refresh_token] = time.time() + _QUOTA_COOLDOWN_SECONDS


def _mask_token(token: str) -> str:
    if len(token) <= 10:
        return token[:2] + "***"
    return f"{token[:6]}...{token[-4:]}"


def get_token_pool_status() -> Dict[str, Any]:
    now = time.time()
    tokens = get_refresh_token_candidates()
    items: List[Dict[str, Any]] = []
    for token in tokens:
        until = _REFRESH_TOKEN_COOLDOWN_UNTIL.get(token, 0.0)
        remaining = max(0.0, until - now)
        items.append(
            {
                "token_preview": _mask_token(token),
                "in_cooldown": remaining > 0,
                "cooldown_remaining_seconds": int(remaining),
            }
        )

    return {
        "token_count": len(tokens),
        "cooldown_seconds": _QUOTA_COOLDOWN_SECONDS,
        "tokens": items,
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
    tried_refresh_tokens: set[str] = set()

    jwt = await get_valid_jwt()
    result = send_warp_protobuf_request(
        body=protobuf_bytes,
        jwt=jwt,
        timeout_seconds=timeout_seconds,
        client_version=client_version or CLIENT_VERSION,
        os_version=os_version or OS_VERSION,
    )
    attempts.append(
        {
            "mode": "current_jwt",
            "status_code": result.get("status_code"),
            "error": str(result.get("error") or "")[:200],
        }
    )
    if result.get("ok") or not _should_rotate_token(result):
        result["attempts"] = attempts
        if model_tag is not None:
            result["model_tag"] = model_tag
        return result

    for refresh_token in get_refresh_token_candidates():
        if refresh_token in tried_refresh_tokens:
            continue
        if _cooldown_active(refresh_token):
            attempts.append({"mode": "refresh_token", "status_code": 0, "error": "token in cooldown"})
            continue
        if len(attempts) >= max_token_attempts:
            break

        tried_refresh_tokens.add(refresh_token)
        try:
            token_data = await refresh_jwt_token(refresh_token_override=refresh_token)
            jwt2 = str(token_data.get("access_token") or token_data.get("id_token") or "").strip()
            if not jwt2:
                attempts.append({"mode": "refresh_token", "status_code": 0, "error": "refresh returned empty token"})
                continue

            result = send_warp_protobuf_request(
                body=protobuf_bytes,
                jwt=jwt2,
                timeout_seconds=timeout_seconds,
                client_version=client_version or CLIENT_VERSION,
                os_version=os_version or OS_VERSION,
            )
            attempts.append(
                {
                    "mode": "refresh_token",
                    "status_code": result.get("status_code"),
                    "error": str(result.get("error") or "")[:200],
                }
            )

            if _is_quota_error(result):
                _mark_cooldown(refresh_token)

            if result.get("ok") or not _should_rotate_token(result):
                result["attempts"] = attempts
                if model_tag is not None:
                    result["model_tag"] = model_tag
                return result
        except Exception as exc:
            attempts.append({"mode": "refresh_token", "status_code": 0, "error": str(exc)[:200]})
            logger.warning("token rotation attempt failed: %s", exc)

    result["attempts"] = attempts
    if model_tag is not None:
        result["model_tag"] = model_tag
    return result
