from __future__ import annotations

from contextlib import asynccontextmanager
import asyncio
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from warp2api.adapters.anthropic.router import router as anthropic_router
from warp2api.adapters.gemini.router import router as gemini_router
from warp2api.adapters.common.logging import logger
from warp2api.api.routes.auth_routes import router as auth_router
from warp2api.api.routes.codec_routes import router as codec_router
from warp2api.api.routes.admin_token_routes import router as admin_token_router
from warp2api.api.routes.model_routes import router as model_router
from warp2api.api.routes.warp_chat_routes import router as warp_chat_router
from warp2api.api.routes.warp_send_routes import router as warp_send_router
from warp2api.api.routes.warp_token_routes import router as warp_token_router
from warp2api.api.routes.ws_routes import router as ws_router
from warp2api.api.runtime import manager
from warp2api.application.services.gateway_access import initialize_once
from warp2api.app.gateway_bootstrap import shutdown_tasks, startup_tasks
from warp2api.infrastructure.runtime.stream_processor import set_websocket_manager
from .router import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        logger.info("[OpenAI Compat] Server starting in unified mode (no bridge relay)")
        logger.info(
            "[OpenAI Compat] Endpoints: GET /healthz, GET /v1/models, POST /v1/chat/completions, "
            "POST /v1/responses, POST /v1/messages, POST /v1/models/{model}:generateContent, "
            "POST /v1/models/{model}:streamGenerateContent"
        )
    except Exception:
        pass

    set_websocket_manager(manager)
    await startup_tasks()

    try:
        await initialize_once()
    except Exception as e:
        logger.warning("[OpenAI Compat] Warmup initialize_once on startup failed: %s", e)
    try:
        yield
    finally:
        try:
            await shutdown_tasks()
        except asyncio.CancelledError:
            pass


app = FastAPI(title="warp2api Multi-Protocol Gateway", lifespan=lifespan)
app.include_router(router)
app.include_router(anthropic_router)
app.include_router(gemini_router)
app.include_router(codec_router)
app.include_router(auth_router)
app.include_router(admin_token_router)
app.include_router(model_router)
app.include_router(warp_chat_router)
app.include_router(warp_send_router)
app.include_router(warp_token_router)
app.include_router(ws_router)

_static_dir = Path("static")
if _static_dir.exists():
    app.mount("/assets", StaticFiles(directory="static"), name="assets")
