from __future__ import annotations

from warp2api.infrastructure.settings.settings import STRICT_ENV, strict_auth_config_ok
from warp2api.observability.logging import logger, set_log_file
from warp2api.infrastructure.monitoring.account_pool_monitor import start_monitor, stop_monitor
from warp2api.infrastructure.token_pool.repository import get_token_repository


async def startup_tasks() -> None:
    logger.info("=" * 60)
    logger.info("warp2api unified gateway starting")
    logger.info("=" * 60)

    try:
        set_log_file("warp_server.log")
    except Exception:
        pass

    try:
        from warp2api.infrastructure.protobuf.runtime import ensure_proto_runtime

        ensure_proto_runtime()
        logger.info("✅ Protobuf runtime initialized")
    except Exception as e:
        logger.error("❌ Protobuf runtime init failed: %s", e)
        raise

    try:
        repo = get_token_repository()
        logger.info("✅ Token pool repository initialized")
    except Exception as e:
        logger.error("❌ Token pool repository init failed: %s", e)
        raise

    if STRICT_ENV:
        stats = repo.statistics()
        has_pool_tokens = int(stats.get("total", 0) or 0) > 0
        if not has_pool_tokens and not strict_auth_config_ok():
            raise RuntimeError(
                "STRICT_ENV enabled but no auth material available. "
                "Please import token accounts in /admin/tokens first."
            )

    try:
        await start_monitor()
    except Exception as e:
        logger.warning("⚠️ token pool monitor start failed: %s", e)


async def shutdown_tasks() -> None:
    try:
        await stop_monitor()
    except Exception as e:
        logger.warning("⚠️ token pool monitor stop failed: %s", e)
