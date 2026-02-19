from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from warp2api.observability.logging import logger
from warp2api.infrastructure.protobuf.utils import dict_to_protobuf_bytes
from warp2api.infrastructure.protobuf.schema_sanitizer import sanitize_mcp_input_schema_in_packet
from warp2api.infrastructure.runtime.stream_processor import set_websocket_manager
from warp2api.api.runtime import manager
from warp2api.api.schemas import EncodeRequest
from warp2api.api.routes.auth_routes import router as auth_router
from warp2api.api.routes.codec_routes import router as codec_router
from warp2api.api.routes.model_routes import router as model_router
from warp2api.api.routes.warp_chat_routes import router as warp_chat_router
from warp2api.api.routes.warp_send_routes import router as warp_send_router
from warp2api.api.routes.warp_token_routes import router as warp_token_router
from warp2api.api.routes.ws_routes import router as ws_router
from warp2api.domain.models.model_catalog import get_all_unique_models
from warp2api.infrastructure.protobuf.codec import encode_smd_inplace

from .bridge_bootstrap import shutdown_tasks, startup_tasks


@asynccontextmanager
async def lifespan(app: FastAPI):
    await startup_tasks()
    try:
        yield
    finally:
        await shutdown_tasks()


def create_app() -> FastAPI:
    set_websocket_manager(manager)
    app = FastAPI(title="Warp Protobuf编解码服务器", version="1.0.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/")
    async def root():
        return {"message": "Warp Protobuf编解码服务器", "version": "1.0.0"}

    @app.get("/healthz")
    async def health_check():
        from datetime import datetime

        return {"status": "ok", "timestamp": datetime.now().isoformat()}

    @app.post("/api/warp/encode_raw")
    async def encode_ai_request_raw(
        request: EncodeRequest,
        output: str = Query(
            "raw",
            description="输出格式：raw(默认，返回application/x-protobuf字节) 或 base64",
            pattern=r"^(raw|base64)$",
        ),
    ):
        try:
            actual_data = request.get_data()
            if not actual_data:
                raise HTTPException(400, "数据包不能为空")

            if isinstance(actual_data, dict):
                wrapped = {"json_data": actual_data}
                wrapped = sanitize_mcp_input_schema_in_packet(wrapped)
                actual_data = wrapped.get("json_data", actual_data)

            actual_data = encode_smd_inplace(actual_data)
            protobuf_bytes = dict_to_protobuf_bytes(actual_data, request.message_type)
            logger.info(f"✅ AI请求编码为protobuf成功: {len(protobuf_bytes)} 字节")

            if output == "raw":
                return Response(
                    content=protobuf_bytes,
                    media_type="application/x-protobuf",
                    headers={"Content-Length": str(len(protobuf_bytes))},
                )

            import base64

            return {
                "protobuf_base64": base64.b64encode(protobuf_bytes).decode("utf-8"),
                "size": len(protobuf_bytes),
                "message_type": request.message_type,
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"❌ AI请求编码失败: {e}")
            raise HTTPException(500, f"编码失败: {str(e)}")

    @app.get("/v1/models")
    async def list_models():
        try:
            models = get_all_unique_models()
            return {"object": "list", "data": models}
        except Exception as e:
            logger.error(f"❌ 获取模型列表失败: {e}")
            raise HTTPException(500, f"获取模型列表失败: {str(e)}")

    static_dir = Path("static")
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory="static"), name="static")
        logger.info("✅ 静态文件服务已启用: /static")

        @app.get("/gui", response_class=HTMLResponse)
        async def serve_gui():
            index_file = static_dir / "index.html"
            if index_file.exists():
                return HTMLResponse(content=index_file.read_text(encoding="utf-8"))
            return HTMLResponse(
                content="""
                <html><body><h1>前端界面文件未找到</h1><p>请确保 static/index.html 文件存在</p></body></html>
                """
            )

    else:
        logger.warning("静态文件目录不存在，GUI界面将不可用")

        @app.get("/gui", response_class=HTMLResponse)
        async def no_gui():
            return HTMLResponse(
                content="""
                <html><body><h1>GUI界面未安装</h1><p>静态文件目录 'static' 不存在</p><p>请创建前端界面文件</p></body></html>
                """
            )

    app.include_router(codec_router)
    app.include_router(auth_router)
    app.include_router(model_router)
    app.include_router(warp_send_router)
    app.include_router(warp_chat_router)
    app.include_router(warp_token_router)
    app.include_router(ws_router)
    return app
