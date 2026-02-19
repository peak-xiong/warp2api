from warp2api.infrastructure.monitoring.account_pool_monitor import get_monitor_status
from warp2api.infrastructure.token_pool.repository import get_token_repository


def test_monitor_status_reads_from_sqlite(monkeypatch, tmp_path):
    db_path = tmp_path / "pool.db"
    monkeypatch.setenv("WARP_TOKEN_DB_PATH", str(db_path))

    repo = get_token_repository()
    repo.upsert_health_snapshot(
        token_id=11,
        token_preview="rt-xx...yy",
        healthy=True,
        last_checked_at=123.0,
        last_success_at=123.0,
        last_error="",
        consecutive_failures=0,
        latency_ms=10,
    )

    status = get_monitor_status()
    assert status["token_count"] >= 1
    assert any(item.get("token_id") == 11 for item in status["items"])

