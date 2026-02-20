#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException

from warp2api.application.services.token_pool_service import get_token_pool_service
from warp2api.observability.logging import logger

router = APIRouter()


@router.get("/api/auth/status")
async def get_auth_status():
    try:
        svc = get_token_pool_service()
        readiness = svc.readiness()
        stats = svc.statistics()
        total = int(stats.get("total", 0) or 0)
        available = int(readiness.get("available_tokens", 0) or 0)
        result = {
            "authenticated": bool(readiness.get("ready")),
            "pool_total_tokens": total,
            "pool_available_tokens": available,
            "readiness": readiness,
            "message": "Token pool ready" if readiness.get("ready") else "Token pool not ready",
        }
        if not readiness.get("ready"):
            result["suggestion"] = "请在 /admin/tokens 导入并刷新可用账号"
        return result
    except Exception as e:
        logger.error(f"❌ 获取认证状态失败: {e}")
        raise HTTPException(500, f"获取认证状态失败: {e}")


@router.post("/api/auth/refresh")
async def refresh_auth_token():
    try:
        svc = get_token_pool_service()
        summary = await svc.refresh_all(actor="system:auth_route")
        success = int(summary.get("failed", 0) or 0) == 0 and int(summary.get("success", 0) or 0) > 0
        if success:
            return {"success": True, "message": "Token pool刷新成功", "timestamp": datetime.now().isoformat(), "data": summary}
        return {
            "success": False,
            "message": "Token pool刷新存在失败",
            "data": summary,
            "suggestion": "检查 /admin/tokens 中 blocked/cooldown 账号",
        }
    except Exception as e:
        logger.error(f"❌ 刷新JWT token失败: {e}")
        raise HTTPException(500, f"刷新token失败: {e}")


@router.get("/api/auth/user_id")
async def get_user_id_endpoint():
    try:
        svc = get_token_pool_service()
        tokens = svc.list_tokens()
        active = [t for t in tokens if str(t.get("status") or "") == "active"]
        email = str((active[0].get("email") if active else "") or "")
        if email:
            return {"success": True, "user_id": email, "message": "User ID获取成功（email）"}
        return {"success": False, "user_id": "", "message": "未找到可用账户标识"}
    except Exception as e:
        logger.error(f"❌ 获取User ID失败: {e}")
        raise HTTPException(500, f"获取User ID失败: {e}")
