from __future__ import annotations

from warp2api.infrastructure.settings.settings import STRICT_ENV, strict_auth_config_ok
from warp2api.infrastructure.auth.jwt_auth import acquire_anonymous_access_token
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
                "Add tokens into token pool (recommended) or set WARP_JWT / WARP_REFRESH_TOKEN_B64."
            )

    try:
        from warp2api.infrastructure.auth.jwt_auth import get_jwt_token, is_token_expired

        token = get_jwt_token()
        if token and not is_token_expired(token):
            logger.info("✅ JWT token is valid")
        elif not token:
            logger.warning("⚠️ JWT token missing; trying anonymous token bootstrap")
            try:
                new_token = await acquire_anonymous_access_token()
                if new_token:
                    logger.info("✅ Anonymous token acquired")
                else:
                    logger.warning("⚠️ Anonymous token acquisition failed")
            except Exception as e2:
                logger.warning("⚠️ Anonymous token bootstrap error: %s", e2)
        else:
            logger.warning("⚠️ JWT token expired/invalid, consider refreshing")
    except Exception as e:
        logger.warning("⚠️ JWT check failed: %s", e)

    try:
        await start_monitor()
    except Exception as e:
        logger.warning("⚠️ token pool monitor start failed: %s", e)


async def shutdown_tasks() -> None:
    try:
        await stop_monitor()
    except Exception as e:
        logger.warning("⚠️ token pool monitor stop failed: %s", e)
