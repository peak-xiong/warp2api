from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import Any, Dict, Optional

import httpx
from fastapi import HTTPException, Request, status

from warp2api.adapters.common.logging import logger

BRIDGE_BASE_URL = os.getenv("WARP_BRIDGE_URL", "http://127.0.0.1:28888")
WARMUP_INIT_RETRIES = int(os.getenv("WARP_COMPAT_INIT_RETRIES", "10"))
WARMUP_INIT_DELAY_S = float(os.getenv("WARP_COMPAT_INIT_DELAY", "0.5"))
WARMUP_REQUEST_RETRIES = int(os.getenv("WARP_COMPAT_WARMUP_RETRIES", "3"))
WARMUP_REQUEST_DELAY_S = float(os.getenv("WARP_COMPAT_WARMUP_DELAY", "1.5"))

_initialized = False
_init_lock = asyncio.Lock()


def _get_expected_token() -> Optional[str]:
    token = (os.getenv("API_TOKEN") or "").strip()
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


async def bridge_send_stream(packet: Dict[str, Any]) -> Dict[str, Any]:
    timeout = httpx.Timeout(connect=5.0, read=180.0, write=30.0, pool=30.0)
    url = f"{BRIDGE_BASE_URL}/api/warp/send_stream"

    async with httpx.AsyncClient(timeout=timeout, trust_env=True) as client:
        wrapped_packet = {"json_data": packet, "message_type": "warp.multi_agent.v1.Request"}
        try:
            logger.info("[Gateway] Bridge request URL: %s", url)
            logger.info("[Gateway] Bridge request payload: %s", json.dumps(wrapped_packet, ensure_ascii=False))
        except Exception:
            logger.info("[Gateway] Bridge request payload serialization failed for URL %s", url)

        resp = await client.post(url, json=wrapped_packet)
        if resp.status_code != 200:
            raise RuntimeError(f"bridge_error: HTTP {resp.status_code} {resp.text}")
        try:
            logger.info("[Gateway] Bridge response (raw text): %s", resp.text)
        except Exception:
            pass
        return resp.json()


async def initialize_once() -> None:
    global _initialized
    if _initialized:
        return

    async with _init_lock:
        if _initialized:
            return

        health_url = f"{BRIDGE_BASE_URL}/healthz"
        timeout = httpx.Timeout(connect=5.0, read=5.0, write=5.0, pool=5.0)

        last_err: Optional[str] = None
        for _ in range(WARMUP_INIT_RETRIES):
            async with httpx.AsyncClient(timeout=timeout, trust_env=True) as client:
                try:
                    resp = await client.get(health_url)
                    if resp.status_code == 200:
                        break
                    last_err = f"HTTP {resp.status_code} at {health_url}"
                except Exception as exc:
                    last_err = f"{type(exc).__name__}: {exc} at {health_url}"
            await asyncio.sleep(WARMUP_INIT_DELAY_S)
        else:
            raise RuntimeError(f"Bridge server not ready: {last_err}")

        from warp2api.application.services.chat_gateway_support import packet_template

        pkt = packet_template()
        pkt["task_context"]["active_task_id"] = str(uuid.uuid4())
        pkt["input"]["user_inputs"]["inputs"].append({"user_query": {"query": "warmup"}})

        for attempt in range(1, WARMUP_REQUEST_RETRIES + 1):
            try:
                await bridge_send_stream(pkt)
                _initialized = True
                return
            except Exception as exc:
                logger.warning("[Gateway] Warmup attempt %s/%s failed: %s", attempt, WARMUP_REQUEST_RETRIES, exc)
                if attempt < WARMUP_REQUEST_RETRIES:
                    await asyncio.sleep(WARMUP_REQUEST_DELAY_S)
                else:
                    raise

