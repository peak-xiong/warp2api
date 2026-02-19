from __future__ import annotations

from warp2api.infrastructure.settings.settings import STRICT_ENV, strict_auth_config_ok
from warp2api.infrastructure.auth.jwt_auth import acquire_anonymous_access_token
from warp2api.observability.logging import logger, set_log_file
from warp2api.infrastructure.monitoring.account_pool_monitor import start_monitor, stop_monitor


async def startup_tasks() -> None:
    logger.info("=" * 60)
    logger.info("Warp Protobuf编解码服务器启动")
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
        logger.info("✅ Protobuf运行时初始化成功")
    except Exception as e:
        logger.error(f"❌ Protobuf运行时初始化失败: {e}")
        raise

    try:
        from warp2api.infrastructure.auth.jwt_auth import get_jwt_token, is_token_expired

        token = get_jwt_token()
        if token and not is_token_expired(token):
            logger.info("✅ JWT token有效")
        elif not token:
            logger.warning("⚠️ 未找到JWT token，尝试申请匿名访问token用于额度初始化…")
            try:
                new_token = await acquire_anonymous_access_token()
                if new_token:
                    logger.info("✅ 匿名访问token申请成功")
                else:
                    logger.warning("⚠️ 匿名访问token申请失败")
            except Exception as e2:
                logger.warning(f"⚠️ 匿名访问token申请异常: {e2}")
        else:
            logger.warning("⚠️ JWT token无效或已过期，建议运行: uv run refresh_jwt.py")
    except Exception as e:
        logger.warning(f"⚠️ JWT检查失败: {e}")

    try:
        await start_monitor()
    except Exception as e:
        logger.warning(f"⚠️ token pool monitor 启动失败: {e}")


async def shutdown_tasks() -> None:
    try:
        await stop_monitor()
    except Exception as e:
        logger.warning(f"⚠️ token pool monitor 停止失败: {e}")
