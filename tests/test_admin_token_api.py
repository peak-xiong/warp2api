import time

from fastapi.testclient import TestClient

from warp2api.app.openai import openai_app


def test_admin_tokens_batch_import_and_list(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "admin-test-token")
    client = TestClient(openai_app)

    token_value = f"rt-{int(time.time() * 1000)}-abcdef"
    headers = {"Authorization": "Bearer admin-test-token"}

    r = client.post(
        "/admin/api/tokens/batch-import",
        json={"tokens": [token_value]},
        headers=headers,
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["inserted"] + data["duplicated"] >= 1

    r2 = client.get("/admin/api/tokens", headers=headers)
    assert r2.status_code == 200
    items = r2.json()["data"]
    assert isinstance(items, list)
    assert any("token_preview" in item for item in items)

    r3 = client.get("/admin/api/tokens/statistics", headers=headers)
    assert r3.status_code == 200
    stats = r3.json()["data"]
    assert "total" in stats
    assert "by_status" in stats

    r4 = client.get("/admin/api/tokens/health", headers=headers)
    assert r4.status_code == 200
    health = r4.json()["data"]
    assert "running" in health
    assert "items" in health

    r5 = client.get("/admin/api/tokens/readiness", headers=headers)
    assert r5.status_code == 200
    readiness = r5.json()["data"]
    assert "ready" in readiness
    assert "available_tokens" in readiness


def test_admin_tokens_requires_admin_token(monkeypatch):
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    client = TestClient(openai_app)
    r = client.get("/admin/api/tokens")
    assert r.status_code == 503


def test_admin_tokens_page_route():
    client = TestClient(openai_app)
    r = client.get("/admin/tokens")
    assert r.status_code == 200
    assert "Token 控制台" in r.text


def test_admin_tokens_local_mode_without_admin_token(monkeypatch):
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    monkeypatch.setenv("WARP_ADMIN_AUTH_MODE", "local")
    client = TestClient(openai_app)
    r = client.get("/admin/api/tokens")
    assert r.status_code == 200


def test_admin_tokens_off_mode_without_admin_token(monkeypatch):
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    monkeypatch.setenv("WARP_ADMIN_AUTH_MODE", "off")
    client = TestClient(openai_app)
    r = client.get("/admin/api/tokens")
    assert r.status_code == 200
