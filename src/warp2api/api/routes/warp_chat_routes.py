#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from warp2api.observability.logging import logger
from warp2api.application.services.token_rotation_service import send_query_with_rotation
from warp2api.domain.models.model_catalog import get_model_config
from ..schemas import MinimalWarpChatRequest

router = APIRouter()


@router.post("/api/warp/simple_chat")
async def send_minimal_warp_chat(request: MinimalWarpChatRequest):
    try:
        if not request.query or not request.query.strip():
            raise HTTPException(400, "query不能为空")

        try:
            model_tag = get_model_config(request.model or "auto")["base"]
        except ValueError as e:
            raise HTTPException(400, str(e))
        result = await send_query_with_rotation(
            request.query,
            model_tag=model_tag,
            timeout_seconds=request.timeout_seconds,
            client_version=request.client_version,
            os_version=request.os_version,
        )
        if not result.get("ok"):
            code = int(result.get("status_code") or 502)
            return JSONResponse(status_code=code, content=result)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Minimal Warp Chat失败: {e}")
        raise HTTPException(500, f"minimal chat失败: {str(e)}")
