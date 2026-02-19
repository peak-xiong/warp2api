#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Shared runtime state for API routes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List

from fastapi import WebSocket

from warp2api.observability.logging import logger


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: List[WebSocket] = []
        self.packet_history: List[Dict] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket连接建立，当前连接数: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info(f"WebSocket连接断开，当前连接数: {len(self.active_connections)}")

    async def broadcast(self, message: Dict) -> None:
        if not self.active_connections:
            return

        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.warning(f"发送WebSocket消息失败: {e}")
                disconnected.append(connection)
        for conn in disconnected:
            self.disconnect(conn)

    async def log_packet(self, packet_type: str, data: Dict, size: int) -> None:
        packet_info = {
            "timestamp": datetime.now().isoformat(),
            "type": packet_type,
            "size": size,
            "data_preview": str(data)[:200] + "..." if len(str(data)) > 200 else str(data),
            "full_data": data,
        }
        self.packet_history.append(packet_info)
        if len(self.packet_history) > 100:
            self.packet_history = self.packet_history[-100:]
        await self.broadcast({"event": "packet_captured", "packet": packet_info})


manager = ConnectionManager()
