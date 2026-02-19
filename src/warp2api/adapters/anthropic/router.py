"""
Anthropic Messages API adapter.
Converts POST /v1/messages (Anthropic format) into internal OpenAI chat completions.
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from warp2api.adapters.common.logging import logger
from warp2api.adapters.common.schemas import (
    ChatCompletionsRequest,
    ChatMessage,
    OpenAIFunctionDef,
    OpenAITool,
)
from warp2api.application.services.chat_gateway_service import execute_chat_completions

router = APIRouter()


def _anthropic_content_to_openai(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif block.get("type") == "image":
                    parts.append("[image]")
                elif block.get("type") == "tool_result":
                    parts.append(str(block.get("content", "")))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return str(content) if content else ""


def _convert_anthropic_to_openai(body: Dict[str, Any]) -> ChatCompletionsRequest:
    messages: List[ChatMessage] = []

    system = body.get("system")
    if system:
        if isinstance(system, list):
            system = "\n".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in system)
        messages.append(ChatMessage(role="system", content=system))

    for msg in body.get("messages", []):
        role = msg.get("role", "user")
        content = msg.get("content", "")

        if role == "user" and isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    messages.append(
                        ChatMessage(
                            role="tool",
                            content=_anthropic_content_to_openai(block.get("content", "")),
                            tool_call_id=block.get("tool_use_id", ""),
                        )
                    )
            text_parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
            if text_parts:
                messages.append(ChatMessage(role="user", content="\n".join(text_parts)))
        else:
            openai_role = "assistant" if role == "assistant" else "user"
            text = _anthropic_content_to_openai(content)
            tool_calls = None
            if role == "assistant" and isinstance(content, list):
                tc_list = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        tc_list.append(
                            {
                                "id": block.get("id", str(uuid.uuid4())),
                                "type": "function",
                                "function": {
                                    "name": block.get("name", ""),
                                    "arguments": json.dumps(block.get("input", {}), ensure_ascii=False),
                                },
                            }
                        )
                if tc_list:
                    tool_calls = tc_list
            messages.append(ChatMessage(role=openai_role, content=text, tool_calls=tool_calls))

    tools = None
    if body.get("tools"):
        tools = []
        for t in body["tools"]:
            tools.append(
                OpenAITool(
                    type="function",
                    function=OpenAIFunctionDef(
                        name=t.get("name", ""),
                        description=t.get("description"),
                        parameters=t.get("input_schema"),
                    ),
                )
            )

    return ChatCompletionsRequest(
        model=body.get("model"),
        messages=messages,
        stream=body.get("stream", False),
        tools=tools,
    )


def _openai_response_to_anthropic(openai_resp: Dict[str, Any], model: str) -> Dict[str, Any]:
    choice = openai_resp.get("choices", [{}])[0]
    msg = choice.get("message", {})
    content_blocks = []

    text = msg.get("content", "")
    if text:
        content_blocks.append({"type": "text", "text": text})

    for tc in msg.get("tool_calls", []):
        func = tc.get("function", {})
        try:
            input_data = json.loads(func.get("arguments", "{}"))
        except Exception:
            input_data = {}
        content_blocks.append(
            {
                "type": "tool_use",
                "id": tc.get("id", str(uuid.uuid4())),
                "name": func.get("name", ""),
                "input": input_data,
            }
        )

    stop_reason = "tool_use" if choice.get("finish_reason") == "tool_calls" else "end_turn"
    return {
        "id": f"msg_{uuid.uuid4().hex[:24]}",
        "type": "message",
        "role": "assistant",
        "content": content_blocks,
        "model": model,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 0, "output_tokens": 0},
    }


async def _openai_sse_to_anthropic_sse(openai_stream, model: str):
    msg_id = f"msg_{uuid.uuid4().hex[:24]}"
    yield f"event: message_start\ndata: {json.dumps({'type': 'message_start', 'message': {'id': msg_id, 'type': 'message', 'role': 'assistant', 'content': [], 'model': model, 'stop_reason': None, 'stop_sequence': None, 'usage': {'input_tokens': 0, 'output_tokens': 0}}})}\n\n"
    yield f"event: content_block_start\ndata: {json.dumps({'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'text', 'text': ''}})}\n\n"

    tool_index = 0
    in_tool = False

    async for chunk_line in openai_stream:
        if not chunk_line.startswith("data: "):
            continue
        payload = chunk_line[6:].strip()
        if payload == "[DONE]":
            break
        try:
            chunk = json.loads(payload)
        except Exception:
            continue

        delta = chunk.get("choices", [{}])[0].get("delta", {})
        finish = chunk.get("choices", [{}])[0].get("finish_reason")

        text = delta.get("content")
        if text:
            yield f"event: content_block_delta\ndata: {json.dumps({'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': text}})}\n\n"

        tcs = delta.get("tool_calls", [])
        for tc in tcs:
            if not in_tool:
                yield f"event: content_block_stop\ndata: {json.dumps({'type': 'content_block_stop', 'index': 0})}\n\n"
                tool_index = 1
                in_tool = True
                func = tc.get("function", {})
                yield f"event: content_block_start\ndata: {json.dumps({'type': 'content_block_start', 'index': tool_index, 'content_block': {'type': 'tool_use', 'id': tc.get('id', ''), 'name': func.get('name', ''), 'input': {}}})}\n\n"
            func = tc.get("function", {})
            args = func.get("arguments", "")
            if args:
                yield f"event: content_block_delta\ndata: {json.dumps({'type': 'content_block_delta', 'index': tool_index, 'delta': {'type': 'input_json_delta', 'partial_json': args}})}\n\n"

        if finish:
            stop_reason = "tool_use" if finish == "tool_calls" else "end_turn"
            current_idx = tool_index if in_tool else 0
            yield f"event: content_block_stop\ndata: {json.dumps({'type': 'content_block_stop', 'index': current_idx})}\n\n"
            yield f"event: message_delta\ndata: {json.dumps({'type': 'message_delta', 'delta': {'stop_reason': stop_reason, 'stop_sequence': None}, 'usage': {'output_tokens': 0}})}\n\n"
            yield f"event: message_stop\ndata: {json.dumps({'type': 'message_stop'})}\n\n"


@router.post("/v1/messages")
async def anthropic_messages(request: Request):
    anthropic_version = request.headers.get("anthropic-version")
    if not anthropic_version:
        raise HTTPException(400, "Missing required header: anthropic-version")

    body = await request.json()
    logger.info("[Anthropic Adapter] Received /v1/messages request for model: %s", body.get("model"))
    if not body.get("model"):
        raise HTTPException(400, "model is required")
    if "max_tokens" not in body:
        raise HTTPException(400, "max_tokens is required")

    openai_req = _convert_anthropic_to_openai(body)
    is_stream = body.get("stream", False)

    if is_stream:
        openai_resp = await execute_chat_completions(openai_req, request)
        if isinstance(openai_resp, StreamingResponse):
            model = body.get("model", "unknown")

            async def _wrap():
                async for chunk in _openai_sse_to_anthropic_sse(openai_resp.body_iterator, model):
                    yield chunk

            return StreamingResponse(
                _wrap(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
            )
        return _openai_response_to_anthropic(openai_resp, body.get("model", "unknown"))

    openai_resp = await execute_chat_completions(openai_req, request)
    if isinstance(openai_resp, dict):
        return _openai_response_to_anthropic(openai_resp, body.get("model", "unknown"))
    return openai_resp
