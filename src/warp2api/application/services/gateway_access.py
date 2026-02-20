from __future__ import annotations

import asyncio
import uuid
from typing import Optional

from fastapi import HTTPException, Request, status

from warp2api.adapters.common.logging import logger
from warp2api.application.services.chat_gateway_support import packet_template
from warp2api.application.services.warp_request_service import execute_warp_packet
from warp2api.infrastructure.settings.settings import (
    CLIENT_VERSION,
    OS_VERSION,
    get_api_token,
    WARP_COMPAT_INIT_DELAY,
    WARP_COMPAT_INIT_RETRIES,
    WARP_COMPAT_STARTUP_WARMUP,
    WARP_COMPAT_WARMUP_DELAY,
    WARP_COMPAT_WARMUP_RETRIES,
)

WARMUP_INIT_RETRIES = WARP_COMPAT_INIT_RETRIES
WARMUP_INIT_DELAY_S = WARP_COMPAT_INIT_DELAY
WARMUP_REQUEST_RETRIES = WARP_COMPAT_WARMUP_RETRIES
WARMUP_REQUEST_DELAY_S = WARP_COMPAT_WARMUP_DELAY
WARMUP_ENABLED = WARP_COMPAT_STARTUP_WARMUP

_initialized = False
_init_lock = asyncio.Lock()


def _get_expected_token() -> Optional[str]:
    token = get_api_token()
    return token or None


def _authenticate_bearer(expected_token: Optional[str], authorization: Optional[str]) -> bool:
    if not expected_token or not authorization or not authorization.startswith("Bearer "):
        return False
    return authorization[7:] == expected_token


async def authenticate_request(request: Request) -> None:
    expected_token = _get_expected_token()
    if not expected_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key provided",
            headers={"WWW-Authenticate": "Bearer"},
        )

    authorization = request.headers.get("authorization") or request.headers.get("Authorization")
    x_api_key = request.headers.get("x-api-key")

    if _authenticate_bearer(expected_token, authorization):
        return
    if x_api_key and x_api_key == expected_token:
        return

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid API key provided",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def initialize_once() -> None:
    global _initialized
    if _initialized:
        return

    async with _init_lock:
        if _initialized:
            return

        if not WARMUP_ENABLED:
            _initialized = True
            logger.info("[Gateway] Startup warmup disabled (WARP_COMPAT_STARTUP_WARMUP=false)")
            return

        # Warm-up the unified protobuf transport path directly.
        pkt = packet_template()
        pkt["task_context"]["active_task_id"] = str(uuid.uuid4())
        pkt["input"]["user_inputs"]["inputs"].append({"user_query": {"query": "warmup"}})

        for attempt in range(1, WARMUP_REQUEST_RETRIES + 1):
            try:
                result = await execute_warp_packet(
                    actual_data=pkt,
                    message_type="warp.multi_agent.v1.Request",
                    timeout_seconds=90,
                    client_version=CLIENT_VERSION,
                    os_version=OS_VERSION,
                )
                raw = result.get("result_raw", {})
                if raw.get("ok"):
                    _initialized = True
                    return
                raise RuntimeError(
                    f"warmup failed: HTTP {raw.get('status_code')} {raw.get('error')}"
                )
            except Exception as exc:
                logger.warning(
                    "[Gateway] Warmup attempt %s/%s failed: %s",
                    attempt,
                    WARMUP_REQUEST_RETRIES,
                    exc,
                )
                if attempt < WARMUP_REQUEST_RETRIES:
                    await asyncio.sleep(WARMUP_REQUEST_DELAY_S)
                else:
                    raise
