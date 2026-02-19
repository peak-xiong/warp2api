#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from warp2api.observability.logging import logger
from ..runtime import manager

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        await websocket.send_json(
            {
                "event": "connected",
                "message": "WebSocket连接已建立",
                "timestamp": datetime.now().isoformat(),
            }
        )
        recent_packets = manager.packet_history[-10:]
        for packet in recent_packets:
            await websocket.send_json({"event": "packet_history", "packet": packet})
        while True:
            data = await websocket.receive_text()
            logger.debug(f"收到WebSocket消息: {data}")
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket错误: {e}")
        manager.disconnect(websocket)
