#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException

from warp2api.observability.logging import logger
from warp2api.domain.models.model_catalog import get_all_unique_models

router = APIRouter()


@router.get("/api/warp/models")
async def get_warp_models_endpoint():
    try:
        models = get_all_unique_models()
        data = [{"id": m["id"], "name": m.get("display_name") or m["id"], "provider": "warp"} for m in models]
        return {"success": True, "data": data}
    except Exception as e:
        logger.error(f"❌ 获取Warp模型列表失败: {e}")
        raise HTTPException(500, f"获取Warp模型列表失败: {e}")


@router.get("/w/v1/models")
async def get_warp_models_openai_endpoint():
    try:
        models = get_all_unique_models()
        data = [
            {
                "id": m["id"],
                "object": "model",
                "created": int(datetime.now().timestamp()),
                "owned_by": "warp",
            }
            for m in models
        ]
        return {"object": "list", "data": data}
    except Exception as e:
        logger.error(f"❌ 获取 /w/v1/models 失败: {e}")
        raise HTTPException(500, f"获取 /w/v1/models 失败: {e}")
