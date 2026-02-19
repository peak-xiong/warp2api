#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException

from warp2api.infrastructure.auth.jwt_auth import get_jwt_token, is_token_expired, refresh_jwt_if_needed
from warp2api.observability.logging import logger

router = APIRouter()


@router.get("/api/auth/status")
async def get_auth_status():
    try:
        jwt_token = get_jwt_token()
        if not jwt_token:
            return {
                "authenticated": False,
                "message": "未找到JWT token",
                "suggestion": "运行 'uv run refresh_jwt.py' 获取token",
            }
        is_expired = is_token_expired(jwt_token)
        result = {
            "authenticated": not is_expired,
            "token_present": True,
            "token_expired": is_expired,
            "token_preview": f"{jwt_token[:20]}...{jwt_token[-10:]}",
            "message": "Token有效" if not is_expired else "Token已过期",
        }
        if is_expired:
            result["suggestion"] = "运行 'uv run refresh_jwt.py' 刷新token"
        return result
    except Exception as e:
        logger.error(f"❌ 获取认证状态失败: {e}")
        raise HTTPException(500, f"获取认证状态失败: {e}")


@router.post("/api/auth/refresh")
async def refresh_auth_token():
    try:
        success = await refresh_jwt_if_needed()
        if success:
            return {"success": True, "message": "JWT token刷新成功", "timestamp": datetime.now().isoformat()}
        return {
            "success": False,
            "message": "JWT token刷新失败",
            "suggestion": "检查网络连接或手动运行 'uv run refresh_jwt.py'",
        }
    except Exception as e:
        logger.error(f"❌ 刷新JWT token失败: {e}")
        raise HTTPException(500, f"刷新token失败: {e}")


@router.get("/api/auth/user_id")
async def get_user_id_endpoint():
    try:
        from warp2api.infrastructure.auth.jwt_auth import get_user_id

        user_id = get_user_id()
        if user_id:
            return {"success": True, "user_id": user_id, "message": "User ID获取成功"}
        return {"success": False, "user_id": "", "message": "未找到User ID，可能需要刷新JWT token"}
    except Exception as e:
        logger.error(f"❌ 获取User ID失败: {e}")
        raise HTTPException(500, f"获取User ID失败: {e}")
