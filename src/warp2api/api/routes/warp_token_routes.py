#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from warp2api.observability.logging import logger
from warp2api.infrastructure.monitoring.account_pool_monitor import get_monitor_status
from warp2api.application.services.token_rotation_service import get_token_pool_status

router = APIRouter()


@router.get("/api/warp/token_pool/status")
async def get_warp_token_pool_status():
    try:
        return {"success": True, "data": get_token_pool_status()}
    except Exception as e:
        logger.error(f"❌ 获取token池状态失败: {e}")
        raise HTTPException(500, f"获取token池状态失败: {e}")


@router.get("/api/warp/token_pool/health")
async def get_warp_token_pool_health():
    try:
        return {"success": True, "data": get_monitor_status()}
    except Exception as e:
        logger.error(f"❌ 获取token池健康状态失败: {e}")
        raise HTTPException(500, f"获取token池健康状态失败: {e}")
