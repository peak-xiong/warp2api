from __future__ import annotations

import json
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from warp2api.adapters.common.schemas import ChatCompletionsRequest
from warp2api.application.services.gateway_access import authenticate_request
from warp2api.application.services.chat_gateway_service import execute_chat_completions
from warp2api.application.services.token_pool_service import get_token_pool_service
from warp2api.application.services.openai_protocol_service import (
    completion_to_responses_payload,
    extract_responses_input_text,
    fetch_models,
    stream_chat_to_responses,
    to_openai_model_list,
)

router = APIRouter()


def _to_openai_model_list(payload):
    # compatibility wrapper for tests/imports
    return to_openai_model_list(payload)


@router.get("/")
def root():
    return {"service": "warp2api Multi-Protocol Gateway", "status": "ok"}


@router.get("/healthz")
async def health_check():
    svc = get_token_pool_service()
    readiness = svc.readiness()
    return {
        "status": "ok",
        "service": "warp2api Multi-Protocol Gateway",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "streaming": {
            "openai_chat_completions": True,
            "openai_responses": True,
            "anthropic_messages": True,
            "gemini_stream_generate_content": True,
        },
        "token_pool_readiness": readiness,
    }


@router.get("/v1/models")
async def list_models():
    return await fetch_models()


@router.post("/v1/chat/completions")
async def chat_completions(req: ChatCompletionsRequest, request: Request = None):
    return await execute_chat_completions(req, request)


@router.post("/v1/responses")
async def responses_api(request: Request):
    await authenticate_request(request)
    body = await request.json()
    model = body.get("model")
    inp = body.get("input")
    stream = bool(body.get("stream", False))

    text = extract_responses_input_text(inp).strip()
    if not text:
        raise HTTPException(400, "input is required")

    chat_req = ChatCompletionsRequest(
        model=model,
        messages=[{"role": "user", "content": text}],
        stream=stream,
    )

    if stream:
        # Minimal Responses stream compatibility.
        chat_stream = await chat_completions(chat_req, request)
        if not isinstance(chat_stream, StreamingResponse):
            payload = completion_to_responses_payload(chat_stream, model or "warp-default")
            async def _single():
                yield f"event: response.completed\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
            return StreamingResponse(_single(), media_type="text/event-stream")

        return StreamingResponse(
            stream_chat_to_responses(chat_stream, model or "warp-default"),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )

    completion = await chat_completions(chat_req, request)
    if not isinstance(completion, dict):
        raise HTTPException(500, "unexpected response type")
    return completion_to_responses_payload(completion, model or "warp-default")
