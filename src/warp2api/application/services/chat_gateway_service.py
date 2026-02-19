from __future__ import annotations

import json
import time
import uuid
from typing import Any, AsyncGenerator, Dict, List

from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse

from warp2api.adapters.common.logging import logger
from warp2api.adapters.common.schemas import ChatCompletionsRequest, ChatMessage
from warp2api.application.services.gateway_access import authenticate_request, initialize_once
from warp2api.application.services.token_rotation_service import send_query_with_rotation
from warp2api.domain.models.model_catalog import get_model_config


def _message_text(msg: ChatMessage) -> str:
    content = msg.content
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: List[str] = []
        for seg in content:
            if isinstance(seg, dict) and seg.get("type") == "text":
                txt = str(seg.get("text") or "").strip()
                if txt:
                    parts.append(txt)
        return "\n".join(parts).strip()
    return ""


def _extract_query(messages: List[ChatMessage]) -> str:
    # Keep behavior deterministic for external clients:
    # use latest user turn as Warp query.
    for msg in reversed(messages):
        if msg.role == "user":
            text = _message_text(msg)
            if text:
                return text
    return ""


def _openai_completion_payload(
    completion_id: str,
    created_ts: int,
    model_id: str,
    text: str,
) -> Dict[str, Any]:
    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": created_ts,
        "model": model_id,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


async def _openai_stream_gen(
    *,
    completion_id: str,
    created_ts: int,
    model_id: str,
    text: str,
) -> AsyncGenerator[str, None]:
    first = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created_ts,
        "model": model_id,
        "choices": [{"index": 0, "delta": {"role": "assistant"}}],
    }
    yield f"data: {json.dumps(first, ensure_ascii=False)}\n\n"

    if text:
        chunk = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created_ts,
            "model": model_id,
            "choices": [{"index": 0, "delta": {"content": text}}],
        }
        yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

    final = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created_ts,
        "model": model_id,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }
    yield f"data: {json.dumps(final, ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"


async def execute_chat_completions(
    req: ChatCompletionsRequest,
    request: Request | None = None,
) -> Dict[str, Any] | StreamingResponse:
    if request:
        await authenticate_request(request)

    try:
        await initialize_once()
    except Exception as exc:
        logger.warning("[Gateway] initialize_once failed or skipped: %s", exc)

    if not req.messages:
        raise HTTPException(400, "messages 不能为空")

    try:
        model_cfg = get_model_config(req.model or "")
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    query = _extract_query(list(req.messages))
    if not query:
        raise HTTPException(400, "messages 中至少需要一条 user 文本消息")

    created_ts = int(time.time())
    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    model_id = req.model or "warp-default"

    result = await send_query_with_rotation(
        query=query,
        model_tag=model_cfg["base"],
        timeout_seconds=90,
    )
    if not result.get("ok"):
        status_code = int(result.get("status_code") or 502)
        raise HTTPException(status_code, f"warp_error: {result.get('error')}")

    response_text = str(result.get("text") or "")

    if req.stream:
        return StreamingResponse(
            _openai_stream_gen(
                completion_id=completion_id,
                created_ts=created_ts,
                model_id=model_id,
                text=response_text,
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )

    return _openai_completion_payload(
        completion_id=completion_id,
        created_ts=created_ts,
        model_id=model_id,
        text=response_text,
    )
