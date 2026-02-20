import asyncio
from pathlib import Path

from warp2api.application.services.token_pool_service import get_token_pool_service
from warp2api.application.services.token_rotation_service import send_protobuf_with_rotation
from warp2api.infrastructure.token_pool.repository import get_token_repository


def test_send_protobuf_uses_token_pool(monkeypatch, tmp_path: Path):
    db_path = tmp_path / "token_pool.db"
    monkeypatch.setenv("WARP_TOKEN_DB_PATH", str(db_path))

    svc = get_token_pool_service()
    svc.batch_import(["rt-test-001"], actor="test")
    token_id = svc.list_tokens()[0]["id"]

    async def _fake_refresh(*args, **kwargs):
        return {"access_token": "jwt-ok"}

    def _fake_send(**kwargs):
        return {"ok": True, "status_code": 200, "response": "ok"}

    monkeypatch.setattr(
        "warp2api.application.services.token_rotation_service.refresh_jwt_token",
        _fake_refresh,
    )
    monkeypatch.setattr(
        "warp2api.application.services.token_rotation_service.send_warp_protobuf_request",
        _fake_send,
    )

    result = asyncio.run(
        send_protobuf_with_rotation(
            protobuf_bytes=b"abc",
            timeout_seconds=10,
            max_token_attempts=2,
            model_tag="auto",
        )
    )

    assert result["ok"] is True
    assert result["attempts"][0]["mode"] == "token_pool"
    assert result["attempts"][0]["token_id"] == token_id


def test_quota_error_sets_quota_exhausted(monkeypatch, tmp_path: Path):
    db_path = tmp_path / "token_pool2.db"
    monkeypatch.setenv("WARP_TOKEN_DB_PATH", str(db_path))

    svc = get_token_pool_service()
    svc.batch_import(["rt-test-002"], actor="test")
    token_id = svc.list_tokens()[0]["id"]

    async def _fake_refresh(*args, **kwargs):
        return {"access_token": "jwt-ok"}

    def _fake_send(**kwargs):
        return {"ok": False, "status_code": 429, "error": "No remaining quota"}

    monkeypatch.setattr(
        "warp2api.application.services.token_rotation_service.refresh_jwt_token",
        _fake_refresh,
    )
    monkeypatch.setattr(
        "warp2api.application.services.token_rotation_service.send_warp_protobuf_request",
        _fake_send,
    )

    result = asyncio.run(
        send_protobuf_with_rotation(
            protobuf_bytes=b"abc",
            timeout_seconds=10,
            max_token_attempts=1,
            model_tag="auto",
        )
    )
    assert result["ok"] is False
    repo = get_token_repository()
    token = repo.get_token(token_id)
    assert token is not None
    assert token["status"] == "quota_exhausted"
    assert token["quota_remaining"] == 0


def test_429_without_quota_text_sets_cooldown(monkeypatch, tmp_path: Path):
    db_path = tmp_path / "token_pool2b.db"
    monkeypatch.setenv("WARP_TOKEN_DB_PATH", str(db_path))

    svc = get_token_pool_service()
    svc.batch_import(["rt-test-002b"], actor="test")
    token_id = svc.list_tokens()[0]["id"]

    async def _fake_refresh(*args, **kwargs):
        return {"access_token": "jwt-ok"}

    def _fake_send(**kwargs):
        return {"ok": False, "status_code": 429, "error": "Too Many Requests"}

    monkeypatch.setattr(
        "warp2api.application.services.token_rotation_service.refresh_jwt_token",
        _fake_refresh,
    )
    monkeypatch.setattr(
        "warp2api.application.services.token_rotation_service.send_warp_protobuf_request",
        _fake_send,
    )

    result = asyncio.run(
        send_protobuf_with_rotation(
            protobuf_bytes=b"abc",
            timeout_seconds=10,
            max_token_attempts=1,
            model_tag="auto",
        )
    )
    assert result["ok"] is False
    repo = get_token_repository()
    token = repo.get_token(token_id)
    assert token is not None
    assert token["status"] == "cooldown"


def test_token_lock_serializes_same_token(monkeypatch, tmp_path: Path):
    db_path = tmp_path / "token_pool3.db"
    monkeypatch.setenv("WARP_TOKEN_DB_PATH", str(db_path))

    svc = get_token_pool_service()
    svc.batch_import(["rt-test-003"], actor="test")

    active = {"n": 0, "max": 0}

    async def _fake_refresh(*args, **kwargs):
        active["n"] += 1
        active["max"] = max(active["max"], active["n"])
        await asyncio.sleep(0.03)
        active["n"] -= 1
        return {"access_token": "jwt-ok"}

    def _fake_send(**kwargs):
        return {"ok": True, "status_code": 200, "response": "ok"}

    monkeypatch.setattr(
        "warp2api.application.services.token_rotation_service.refresh_jwt_token",
        _fake_refresh,
    )
    monkeypatch.setattr(
        "warp2api.application.services.token_rotation_service.send_warp_protobuf_request",
        _fake_send,
    )

    async def _run_two():
        await asyncio.gather(
            send_protobuf_with_rotation(protobuf_bytes=b"a", timeout_seconds=10, max_token_attempts=1, model_tag="auto"),
            send_protobuf_with_rotation(protobuf_bytes=b"b", timeout_seconds=10, max_token_attempts=1, model_tag="auto"),
        )

    asyncio.run(_run_two())
    assert active["max"] == 1


def test_empty_pool_returns_503_without_env_fallback(monkeypatch, tmp_path: Path):
    db_path = tmp_path / "token_pool_empty.db"
    monkeypatch.setenv("WARP_TOKEN_DB_PATH", str(db_path))

    async def _boom_refresh(*args, **kwargs):
        raise RuntimeError("should not be called")

    monkeypatch.setattr(
        "warp2api.application.services.token_rotation_service.refresh_jwt_token",
        _boom_refresh,
    )

    result = asyncio.run(
        send_protobuf_with_rotation(
            protobuf_bytes=b"abc",
            timeout_seconds=10,
            max_token_attempts=2,
            model_tag="auto",
        )
    )
    assert result["ok"] is False
    assert result["status_code"] == 503
    assert "token pool" in result["error"]
    assert result["attempts"] == []


def test_scheduler_rotates_tokens_more_evenly(monkeypatch, tmp_path: Path):
    db_path = tmp_path / "token_pool_rr.db"
    monkeypatch.setenv("WARP_TOKEN_DB_PATH", str(db_path))

    svc = get_token_pool_service()
    svc.batch_import(["rt-rr-001", "rt-rr-002"], actor="test")

    async def _fake_refresh(*args, **kwargs):
        return {"access_token": "jwt-ok"}

    def _fake_send(**kwargs):
        return {"ok": True, "status_code": 200, "response": "ok"}

    monkeypatch.setattr(
        "warp2api.application.services.token_rotation_service.refresh_jwt_token",
        _fake_refresh,
    )
    monkeypatch.setattr(
        "warp2api.application.services.token_rotation_service.send_warp_protobuf_request",
        _fake_send,
    )

    r1 = asyncio.run(
        send_protobuf_with_rotation(
            protobuf_bytes=b"a",
            timeout_seconds=10,
            max_token_attempts=1,
            model_tag="auto",
        )
    )
    r2 = asyncio.run(
        send_protobuf_with_rotation(
            protobuf_bytes=b"b",
            timeout_seconds=10,
            max_token_attempts=1,
            model_tag="auto",
        )
    )

    id1 = r1["attempts"][0]["token_id"]
    id2 = r2["attempts"][0]["token_id"]
    assert id1 != id2


def test_scheduler_skips_unhealthy_tokens(monkeypatch, tmp_path: Path):
    db_path = tmp_path / "token_pool_unhealthy.db"
    monkeypatch.setenv("WARP_TOKEN_DB_PATH", str(db_path))

    svc = get_token_pool_service()
    svc.batch_import(["rt-h-001", "rt-h-002"], actor="test")
    items = svc.list_tokens()
    bad_id = int(items[0]["id"])
    good_id = int(items[1]["id"])

    repo = get_token_repository()
    repo.upsert_health_snapshot(
        token_id=bad_id,
        healthy=False,
        last_checked_at=123.0,
        last_success_at=0.0,
        last_error="simulated",
        consecutive_failures=4,
        latency_ms=10,
    )

    async def _fake_refresh(*args, **kwargs):
        return {"access_token": "jwt-ok"}

    def _fake_send(**kwargs):
        return {"ok": True, "status_code": 200, "response": "ok"}

    monkeypatch.setattr(
        "warp2api.application.services.token_rotation_service.refresh_jwt_token",
        _fake_refresh,
    )
    monkeypatch.setattr(
        "warp2api.application.services.token_rotation_service.send_warp_protobuf_request",
        _fake_send,
    )

    result = asyncio.run(
        send_protobuf_with_rotation(
            protobuf_bytes=b"x",
            timeout_seconds=10,
            max_token_attempts=1,
            model_tag="auto",
        )
    )
    assert result["attempts"][0]["token_id"] == good_id


def test_refresh_token_merges_duplicate_refresh_token(monkeypatch, tmp_path: Path):
    db_path = tmp_path / "token_pool_merge.db"
    monkeypatch.setenv("WARP_TOKEN_DB_PATH", str(db_path))

    svc = get_token_pool_service()
    svc.batch_import(["rt-merge-a", "rt-merge-b"], actor="test")
    items = svc.list_tokens()
    ids = {item["warp_refresh_token"]: int(item["id"]) for item in items}
    id_a = ids["rt-merge-a"]
    id_b = ids["rt-merge-b"]

    async def _fake_refresh(*args, **kwargs):
        return {"access_token": "jwt-ok", "refresh_token": "rt-merge-a"}

    monkeypatch.setattr(
        "warp2api.application.services.token_pool_service.refresh_jwt_token",
        _fake_refresh,
    )

    result = asyncio.run(svc.refresh_token(id_b, actor="test"))
    assert result["success"] is True
    assert int(result["token"]["id"]) == id_a

    repo = get_token_repository()
    merged_source = repo.get_token(id_b)
    merged_target = repo.get_token(id_a)
    assert merged_source is None
    assert merged_target is not None
    assert merged_target["status"] == "active"
