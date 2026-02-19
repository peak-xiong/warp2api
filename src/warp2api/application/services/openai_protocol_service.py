from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, List

from fastapi.responses import StreamingResponse

from warp2api.domain.models.model_catalog import get_all_unique_models


def to_openai_model_list(payload: Any) -> Dict[str, Any]:
    items = []
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        items = payload["data"]
    elif isinstance(payload, list):
        items = payload
    out = []
    now = int(time.time())
    for item in items:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id") or "").strip()
        if not model_id:
            continue
        out.append(
            {
                "id": model_id,
                "object": "model",
                "created": int(item.get("created") or now),
                "owned_by": str(item.get("owned_by") or "warp"),
            }
        )
    return {"object": "list", "data": out}


async def fetch_models() -> Dict[str, Any]:
    return to_openai_model_list(get_all_unique_models())


def extract_responses_input_text(inp: Any) -> str:
    if isinstance(inp, str):
        return inp
    if isinstance(inp, list):
        chunks: List[str] = []
        for item in inp:
            if isinstance(item, str):
                chunks.append(item)
                continue
            if not isinstance(item, dict):
                continue
            if item.get("type") == "input_text":
                chunks.append(str(item.get("text") or ""))
                continue
            if item.get("type") == "message":
                content = item.get("content")
                if isinstance(content, str):
                    chunks.append(content)
                elif isinstance(content, list):
                    for c in content:
                        if isinstance(c, dict) and c.get("type") in ("input_text", "text"):
                            chunks.append(str(c.get("text") or ""))
        return "\n".join([c for c in chunks if c])
    return ""


def completion_to_responses_payload(completion: Dict[str, Any], model_id: str) -> Dict[str, Any]:
    choices = completion.get("choices", []) or []
    first = choices[0] if choices else {}
    message = first.get("message", {}) or {}
    text = str(message.get("content") or "")
    return {
        "id": f"resp_{uuid.uuid4().hex}",
        "object": "response",
        "created_at": int(time.time()),
        "status": "completed",
        "model": model_id,
        "output": [
            {
                "id": f"msg_{uuid.uuid4().hex}",
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": text, "annotations": []}],
            }
        ],
        "output_text": text,
        "usage": completion.get("usage", {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}),
    }


async def stream_chat_to_responses(chat_stream: StreamingResponse, model: str):
    accumulated = ""
    async for line in chat_stream.body_iterator:
        if not line.startswith("data: "):
            continue
        payload = line[6:].strip()
        if payload == "[DONE]":
            done = {
                "type": "response.completed",
                "response": {
                    "id": f"resp_{uuid.uuid4().hex}",
                    "object": "response",
                    "status": "completed",
                    "model": model,
                    "output_text": accumulated,
                },
            }
            yield f"event: response.completed\ndata: {json.dumps(done, ensure_ascii=False)}\n\n"
            break
        try:
            chunk = json.loads(payload)
        except Exception:
            continue
        delta = ((chunk.get("choices") or [{}])[0].get("delta") or {})
        dtext = delta.get("content")
        if dtext:
            accumulated += dtext
            evt = {"type": "response.output_text.delta", "delta": dtext}
            yield f"event: response.output_text.delta\ndata: {json.dumps(evt, ensure_ascii=False)}\n\n"
