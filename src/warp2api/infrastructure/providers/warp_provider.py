from __future__ import annotations

from typing import Any, Dict, Optional

from warp2api.application.services.token_rotation_service import (
    send_protobuf_with_rotation,
    send_query_with_rotation,
)


async def send_query(query: str, model_tag: str, timeout_seconds: int = 90) -> Dict[str, Any]:
    return await send_query_with_rotation(query=query, model_tag=model_tag, timeout_seconds=timeout_seconds)


async def send_protobuf(payload: bytes, timeout_seconds: int = 90, model_tag: Optional[str] = None) -> Dict[str, Any]:
    return await send_protobuf_with_rotation(
        protobuf_bytes=payload,
        timeout_seconds=timeout_seconds,
        model_tag=model_tag,
    )
