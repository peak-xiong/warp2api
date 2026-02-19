from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse

from warp2api.adapters.common.logging import logger
from warp2api.adapters.common.schemas import ChatCompletionsRequest, ChatMessage
from warp2api.application.services.gateway_access import authenticate_request, initialize_once
from warp2api.application.services.chat_gateway_support import (
    attach_user_and_tools_to_inputs,
    extract_tool_call_deltas,
    get_state_for_request,
    map_history_to_warp_messages,
    normalize_content_to_list,
    packet_template,
    reorder_messages_for_anthropic,
    segments_to_text,
    stream_openai_sse,
)
from warp2api.application.services.warp_request_service import execute_warp_packet
from warp2api.infrastructure.settings.settings import CLIENT_VERSION, OS_VERSION
from warp2api.domain.models.model_catalog import get_model_config


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
        logger.info("[Gateway] 接收到的 Chat Completions 请求体(原始): %s", json.dumps(req.model_dump(), ensure_ascii=False))
    except Exception:
        logger.info("[Gateway] 接收到的 Chat Completions 请求体(原始) 序列化失败")

    history: List[ChatMessage] = reorder_messages_for_anthropic(list(req.messages))

    try:
        logger.info(
            "[Gateway] 整理后的请求体(post-reorder): %s",
            json.dumps({**req.model_dump(), "messages": [m.model_dump() for m in history]}, ensure_ascii=False),
        )
    except Exception:
        logger.info("[Gateway] 整理后的请求体(post-reorder) 序列化失败")

    system_prompt_text: Optional[str] = None
    try:
        chunks: List[str] = []
        for item in history:
            if item.role == "system":
                text = segments_to_text(normalize_content_to_list(item.content))
                if text.strip():
                    chunks.append(text)
        if chunks:
            system_prompt_text = "\n\n".join(chunks)
    except Exception:
        system_prompt_text = None

    headers = dict(request.headers) if request else None
    state = get_state_for_request(headers)
    task_id = state.baseline_task_id or str(uuid.uuid4())

    packet = packet_template()
    packet["task_context"] = {
        "tasks": [
            {
                "id": task_id,
                "description": "",
                "status": {"in_progress": {}},
                "messages": map_history_to_warp_messages(history, task_id, state=state),
            }
        ],
        "active_task_id": task_id,
    }

    packet.setdefault("settings", {}).setdefault("model_config", {})
    try:
        model_cfg = get_model_config(req.model or "")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    packet["settings"]["model_config"]["base"] = model_cfg["base"]
    packet["settings"]["model_config"]["planning"] = model_cfg["planning"]
    packet["settings"]["model_config"]["coding"] = model_cfg["coding"]

    if state.conversation_id:
        packet.setdefault("metadata", {})["conversation_id"] = state.conversation_id

    attach_user_and_tools_to_inputs(packet, history, system_prompt_text)

    if req.tools:
        mcp_tools: List[Dict[str, Any]] = []
        for tool in req.tools:
            if tool.type != "function" or not tool.function:
                continue
            mcp_tools.append(
                {
                    "name": tool.function.name,
                    "description": tool.function.description or "",
                    "input_schema": tool.function.parameters or {},
                }
            )
        if mcp_tools:
            packet.setdefault("mcp_context", {}).setdefault("tools", []).extend(mcp_tools)

    try:
        logger.info("[Gateway] 转换成 Protobuf JSON 的请求体: %s", json.dumps(packet, ensure_ascii=False))
    except Exception:
        logger.info("[Gateway] 转换成 Protobuf JSON 的请求体 序列化失败")

    created_ts = int(time.time())
    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    model_id = req.model or "warp-default"

    if req.stream:
        async def _agen():
            async for chunk in stream_openai_sse(packet, completion_id, created_ts, model_id):
                yield chunk

        return StreamingResponse(
            _agen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )

    exec_ctx = await execute_warp_packet(
        actual_data=packet,
        message_type="warp.multi_agent.v1.Request",
        timeout_seconds=90,
        client_version=CLIENT_VERSION,
        os_version=OS_VERSION,
    )
    bridge_resp = exec_ctx["result_raw"]
    if not bridge_resp.get("ok"):
        status_code = int(bridge_resp.get("status_code") or 502)
        raise HTTPException(status_code, f"warp_error: {bridge_resp.get('error')}")

    try:
        state.conversation_id = bridge_resp.get("conversation_id") or state.conversation_id
        ret_task_id = bridge_resp.get("task_id")
        if isinstance(ret_task_id, str) and ret_task_id:
            state.baseline_task_id = ret_task_id
    except Exception:
        pass

    tool_calls: List[Dict[str, Any]] = []
    try:
        parsed_events = bridge_resp.get("parsed_events", []) or []
        for ev in parsed_events:
            evd = ev.get("parsed_data") or ev.get("raw_data") or {}
            for tc in extract_tool_call_deltas(evd):
                tool_calls.append(tc)
    except Exception:
        pass

    if tool_calls:
        msg_payload = {"role": "assistant", "content": "", "tool_calls": tool_calls}
        finish_reason = "tool_calls"
    else:
        response_text = bridge_resp.get("response", "")
        msg_payload = {"role": "assistant", "content": response_text}
        finish_reason = "stop"

    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": created_ts,
        "model": model_id,
        "choices": [{"index": 0, "message": msg_payload, "finish_reason": finish_reason}],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
    }
