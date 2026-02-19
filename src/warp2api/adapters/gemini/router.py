"""
Google Gemini API adapter.
Converts Gemini generateContent requests into internal OpenAI chat completions.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from warp2api.adapters.common.logging import logger
from warp2api.adapters.common.schemas import ChatCompletionsRequest, ChatMessage
from warp2api.application.services.chat_gateway_service import execute_chat_completions

router = APIRouter()


def _gemini_parts_to_text(parts: List[Dict]) -> str:
    texts = []
    for part in parts:
        if isinstance(part, dict) and "text" in part:
            texts.append(part["text"])
    return "\n".join(texts)


def _gemini_role_to_openai(role: str) -> str:
    mapping = {"user": "user", "model": "assistant"}
    return mapping.get(role, "user")


def _convert_gemini_to_openai(body: Dict[str, Any], model: str) -> ChatCompletionsRequest:
    messages: List[ChatMessage] = []

    sys_inst = body.get("systemInstruction") or body.get("system_instruction")
    if sys_inst:
        parts = sys_inst.get("parts", [])
        text = _gemini_parts_to_text(parts) if parts else ""
        if text:
            messages.append(ChatMessage(role="system", content=text))

    for content in body.get("contents", []):
        role = _gemini_role_to_openai(content.get("role", "user"))
        parts = content.get("parts", [])
        text = _gemini_parts_to_text(parts)
        if text:
            messages.append(ChatMessage(role=role, content=text))

    return ChatCompletionsRequest(model=model, messages=messages, stream=body.get("stream", False))


def _openai_response_to_gemini(openai_resp: Dict[str, Any], model: str) -> Dict[str, Any]:
    choice = openai_resp.get("choices", [{}])[0]
    msg = choice.get("message", {})
    text = msg.get("content", "")

    return {
        "candidates": [{"content": {"parts": [{"text": text}], "role": "model"}, "finishReason": "STOP", "index": 0}],
        "usageMetadata": {"promptTokenCount": 0, "candidatesTokenCount": 0, "totalTokenCount": 0},
        "modelVersion": model,
    }


async def _openai_sse_to_gemini_sse(openai_stream, model: str):
    async for chunk_line in openai_stream:
        if not chunk_line.startswith("data: "):
            continue
        payload = chunk_line[6:].strip()
        if payload == "[DONE]":
            final = {"candidates": [{"content": {"parts": [{"text": ""}], "role": "model"}, "finishReason": "STOP"}]}
            yield f"data: {json.dumps(final)}\n\n"
            break
        try:
            chunk = json.loads(payload)
        except Exception:
            continue

        delta = chunk.get("choices", [{}])[0].get("delta", {})
        text = delta.get("content", "")
        if text:
            gemini_chunk = {
                "candidates": [{"content": {"parts": [{"text": text}], "role": "model"}, "index": 0}],
                "modelVersion": model,
            }
            yield f"data: {json.dumps(gemini_chunk)}\n\n"


@router.post("/v1/models/{model_name}:generateContent")
async def gemini_generate(model_name: str, request: Request):
    body = await request.json()
    logger.info("[Gemini Adapter] Received generateContent for model: %s", model_name)

    openai_req = _convert_gemini_to_openai(body, model_name)
    openai_resp = await execute_chat_completions(openai_req, request)

    if isinstance(openai_resp, dict):
        return _openai_response_to_gemini(openai_resp, model_name)
    return openai_resp


@router.post("/v1beta/models/{model_name}:generateContent")
async def gemini_generate_v1beta(model_name: str, request: Request):
    return await gemini_generate(model_name, request)


@router.post("/v1/models/{model_name}:streamGenerateContent")
async def gemini_stream_generate(model_name: str, request: Request):
    body = await request.json()
    body["stream"] = True
    logger.info("[Gemini Adapter] Received streamGenerateContent for model: %s", model_name)

    openai_req = _convert_gemini_to_openai(body, model_name)
    openai_resp = await execute_chat_completions(openai_req, request)

    if isinstance(openai_resp, StreamingResponse):
        async def _wrap():
            async for chunk in _openai_sse_to_gemini_sse(openai_resp.body_iterator, model_name):
                yield chunk

        return StreamingResponse(
            _wrap(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )

    if isinstance(openai_resp, dict):
        return _openai_response_to_gemini(openai_resp, model_name)
    return openai_resp


@router.post("/v1beta/models/{model_name}:streamGenerateContent")
async def gemini_stream_generate_v1beta(model_name: str, request: Request):
    return await gemini_stream_generate(model_name, request)
