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

    if STRICT_ENV and not strict_auth_config_ok():
        raise RuntimeError(
            "STRICT_ENV enabled but no auth material provided. "
            "Set one of WARP_JWT / WARP_REFRESH_TOKEN / WARP_REFRESH_TOKENS / WARP_REFRESH_TOKEN_B64."
        )

    try:
        from warp2api.infrastructure.protobuf.runtime import ensure_proto_runtime

        ensure_proto_runtime()
        logger.info("✅ Protobuf runtime initialized")
    except Exception as e:
        logger.error("❌ Protobuf runtime init failed: %s", e)
        raise

    try:
        _ = get_token_repository()
        logger.info("✅ Token pool repository initialized")
    except Exception as e:
        logger.error("❌ Token pool repository init failed: %s", e)
        raise

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
