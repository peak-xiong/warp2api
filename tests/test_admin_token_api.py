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
    assert any("warp_refresh_token" in item for item in items)

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
    monkeypatch.setenv("WARP_ADMIN_AUTH_MODE", "token")
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


def test_admin_tokens_delete(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "admin-test-token")
    client = TestClient(openai_app)
    headers = {"Authorization": "Bearer admin-test-token"}

    token_value = f"rt-delete-{int(time.time() * 1000)}-abcd"
    r1 = client.post(
        "/admin/api/tokens/batch-import",
        json={"tokens": [token_value]},
        headers=headers,
    )
    assert r1.status_code == 200

    r2 = client.get("/admin/api/tokens", headers=headers)
    assert r2.status_code == 200
    token_id = int(r2.json()["data"][0]["id"])

    r3 = client.delete(f"/admin/api/tokens/{token_id}", headers=headers)
    assert r3.status_code == 200
    assert r3.json()["data"]["deleted"] is True

    r4 = client.get(f"/admin/api/tokens/{token_id}", headers=headers)
    assert r4.status_code == 404


def test_admin_tokens_batch_delete(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "admin-test-token")
    monkeypatch.setenv("WARP_ADMIN_AUTH_MODE", "token")
    client = TestClient(openai_app)
    headers = {"Authorization": "Bearer admin-test-token"}

    before_items = client.get("/admin/api/tokens", headers=headers).json()["data"]
    before_ids = {int(x["id"]) for x in before_items}

    t1 = f"rt-batch-del-{int(time.time() * 1000)}-1"
    t2 = f"rt-batch-del-{int(time.time() * 1000)}-2"
    r1 = client.post(
        "/admin/api/tokens/batch-import",
        json={"tokens": [t1, t2]},
        headers=headers,
    )
    assert r1.status_code == 200

    after_items = client.get("/admin/api/tokens", headers=headers).json()["data"]
    new_ids = [int(x["id"]) for x in after_items if int(x["id"]) not in before_ids]
    assert len(new_ids) >= 2
    ids = new_ids[:2]

    r2 = client.post(
        "/admin/api/tokens/batch-delete",
        json={"ids": ids},
        headers=headers,
    )
    assert r2.status_code == 200
    assert r2.json()["data"]["deleted"] == 2


def test_admin_tokens_batch_import_accounts_json(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "admin-test-token")
    monkeypatch.setenv("WARP_ADMIN_AUTH_MODE", "token")
    client = TestClient(openai_app)
    headers = {"Authorization": "Bearer admin-test-token"}

    token_value = f"rt-acc-{int(time.time() * 1000)}-abcdef"
    payload = {
        "accounts": [
            {
                "refresh_token": token_value,
                "email": "demo@example.com",
                "api_key": "wk-1.demo",
                "id_token": "eyJ.demo",
                "total_limit": 300,
                "used_limit": 0,
            }
        ]
    }
    r1 = client.post("/admin/api/tokens/batch-import", json=payload, headers=headers)
    assert r1.status_code == 200
    data = r1.json()["data"]
    assert data["inserted"] + data["duplicated"] >= 1

    items = client.get("/admin/api/tokens", headers=headers).json()["data"]
    hit = next((x for x in items if x.get("warp_refresh_token") == token_value), None)
    assert hit is not None
    assert hit["email"] == "demo@example.com"
    assert hit["api_key"] == "wk-1.demo"
    assert hit["id_token"] == "eyJ.demo"
    assert hit["total_limit"] == 300
    assert hit["used_limit"] == 0
