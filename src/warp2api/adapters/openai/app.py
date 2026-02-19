from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from warp2api.adapters.anthropic.router import router as anthropic_router
from warp2api.adapters.gemini.router import router as gemini_router
from warp2api.adapters.common.logging import logger
from warp2api.application.services.bridge_access import (
    BRIDGE_BASE_URL,
    WARMUP_INIT_DELAY_S,
    WARMUP_INIT_RETRIES,
    initialize_once,
)
from .router import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        logger.info("[OpenAI Compat] Server starting. BRIDGE_BASE_URL=%s", BRIDGE_BASE_URL)
        logger.info(
            "[OpenAI Compat] Endpoints: GET /healthz, GET /v1/models, POST /v1/chat/completions, "
            "POST /v1/responses, POST /v1/messages, POST /v1/models/{model}:generateContent, "
            "POST /v1/models/{model}:streamGenerateContent"
        )
    except Exception:
        pass

    url = f"{BRIDGE_BASE_URL}/healthz"
    retries = WARMUP_INIT_RETRIES
    delay_s = WARMUP_INIT_DELAY_S
    for attempt in range(1, retries + 1):
        try:
            async with httpx.AsyncClient(timeout=5.0, trust_env=True) as client:
                resp = await client.get(url)
            if resp.status_code == 200:
                logger.info("[OpenAI Compat] Bridge server is ready at %s", url)
                break
            logger.warning("[OpenAI Compat] Bridge health at %s -> HTTP %s", url, resp.status_code)
        except Exception as e:
            logger.warning("[OpenAI Compat] Bridge health attempt %s/%s failed: %s", attempt, retries, e)
        await asyncio.sleep(delay_s)
    else:
        logger.error("[OpenAI Compat] Bridge server not ready at %s", url)

    try:
        await initialize_once()
    except Exception as e:
        logger.warning("[OpenAI Compat] Warmup initialize_once on startup failed: %s", e)
    yield


app = FastAPI(title="OpenAI Chat Completions (Warp bridge) - Streaming", lifespan=lifespan)
app.include_router(router)
app.include_router(anthropic_router)
app.include_router(gemini_router)
