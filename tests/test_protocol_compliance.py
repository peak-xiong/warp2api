import os
import json

from fastapi.testclient import TestClient
from fastapi.responses import StreamingResponse

from warp2api.adapters.openai.app import app as openai_app
import warp2api.adapters.openai.router as openai_router
from warp2api.adapters.openai.router import _to_openai_model_list


def test_openai_model_list_normalization():
    payload = {
        "data": [
            {"id": "gpt-5", "owned_by": "warp", "created": 123},
            {"id": "claude-4.1-opus"},
        ]
    }
    out = _to_openai_model_list(payload)
    assert out["object"] == "list"
    assert len(out["data"]) == 2
    assert out["data"][0]["object"] == "model"
    assert "id" in out["data"][0]
    assert "owned_by" in out["data"][0]


def test_anthropic_messages_requires_version_header():
    c = TestClient(openai_app)
    r = c.post("/v1/messages", json={"model": "claude-4.1-opus", "max_tokens": 100, "messages": []})
    assert r.status_code == 400
    assert "anthropic-version" in r.text


def test_anthropic_messages_requires_max_tokens():
    c = TestClient(openai_app)
    headers = {"anthropic-version": "2023-06-01"}
    r = c.post("/v1/messages", headers=headers, json={"model": "claude-4.1-opus", "messages": []})
    assert r.status_code == 400
    assert "max_tokens" in r.text


def test_gemini_v1beta_routes_exist(monkeypatch):
    monkeypatch.setenv("API_TOKEN", "test-token")
    c = TestClient(openai_app)
    body = {"contents": [{"role": "user", "parts": [{"text": "hi"}]}]}
    r1 = c.post("/v1beta/models/gemini-2.5-pro:generateContent", json=body)
    r2 = c.post("/v1beta/models/gemini-2.5-pro:streamGenerateContent", json=body)
    # either auth failure (if header absent) or upstream/validation response, but route must exist
    assert r1.status_code != 404
    assert r2.status_code != 404


def test_openai_responses_non_stream_shape(monkeypatch):
    monkeypatch.setenv("API_TOKEN", "test-token")

    async def _fake_chat(req, request=None):
        return {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 123,
            "model": req.model or "gpt-5",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "hello"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

    monkeypatch.setattr(openai_router, "chat_completions", _fake_chat)
    c = TestClient(openai_app)
    r = c.post(
        "/v1/responses",
        headers={"Authorization": "Bearer test-token"},
        json={"model": "gpt-5", "input": "hi"},
    )
    assert r.status_code == 200
    j = r.json()
    assert j["object"] == "response"
    assert j["status"] == "completed"
    assert isinstance(j.get("output"), list)
    assert isinstance(j.get("output_text"), str)


def test_openai_responses_stream_shape(monkeypatch):
    monkeypatch.setenv("API_TOKEN", "test-token")

    async def _fake_chat(req, request=None):
        async def _agen():
            chunk1 = {
                "id": "chatcmpl-test",
                "object": "chat.completion.chunk",
                "created": 123,
                "model": req.model or "gpt-5",
                "choices": [{"index": 0, "delta": {"content": "he"}}],
            }
            chunk2 = {
                "id": "chatcmpl-test",
                "object": "chat.completion.chunk",
                "created": 123,
                "model": req.model or "gpt-5",
                "choices": [{"index": 0, "delta": {"content": "llo"}}],
            }
            yield f"data: {json.dumps(chunk1)}\n\n"
            yield f"data: {json.dumps(chunk2)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(_agen(), media_type="text/event-stream")

    monkeypatch.setattr(openai_router, "chat_completions", _fake_chat)
    c = TestClient(openai_app)
    r = c.post(
        "/v1/responses",
        headers={"Authorization": "Bearer test-token"},
        json={"model": "gpt-5", "input": "hi", "stream": True},
    )
    assert r.status_code == 200
    assert "response.output_text.delta" in r.text
    assert "response.completed" in r.text
