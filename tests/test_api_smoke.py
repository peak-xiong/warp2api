from fastapi.testclient import TestClient

from warp2api.app.bridge import app


client = TestClient(app)


def test_healthz_ok():
    r = client.get("/healthz")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"


def test_models_endpoints_ok():
    r1 = client.get("/api/warp/models")
    assert r1.status_code == 200
    assert isinstance(r1.json().get("data"), list)

    r2 = client.get("/w/v1/models")
    assert r2.status_code == 200
    assert isinstance(r2.json().get("data"), list)


def test_encode_ok():
    payload = {
        "message_type": "warp.multi_agent.v1.Request",
        "json_data": {
            "task_context": {"active_task_id": "t1"},
            "input": {
                "context": {},
                "user_inputs": {"inputs": [{"user_query": {"query": "warmup"}}]},
            },
            "settings": {"model_config": {"base": "auto"}},
        },
    }
    r = client.post("/api/encode", json=payload)
    assert r.status_code == 200
    j = r.json()
    assert isinstance(j.get("protobuf_bytes"), str)
    assert j.get("size", 0) > 0


def test_simple_chat_invalid_model_returns_400():
    r = client.post("/api/warp/simple_chat", json={"query": "hi", "model": "model-not-exists"})
    assert r.status_code == 400


def test_token_pool_status_ok():
    r = client.get("/api/warp/token_pool/status")
    assert r.status_code == 200
    j = r.json()
    assert j.get("success") is True
    assert "data" in j


def test_token_pool_health_ok():
    r = client.get("/api/warp/token_pool/health")
    assert r.status_code == 200
    j = r.json()
    assert j.get("success") is True
    assert "data" in j
