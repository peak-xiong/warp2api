#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Configuration settings for Warp API server.
"""

import os
import pathlib

from dotenv import load_dotenv

load_dotenv()

ROOT_DIR = pathlib.Path(__file__).resolve().parents[4]
PROTO_DIR = ROOT_DIR / "src" / "warp2api" / "proto"
LOGS_DIR = ROOT_DIR / "logs"

WARP_URL = "https://app.warp.dev/ai/multi-agent"

def _env_str(name: str, default: str = "") -> str:
    return str(os.getenv(name, default))


def _env_bool(name: str, default: bool = False) -> bool:
    raw = _env_str(name, "true" if default else "false").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, min_value: int | None = None, max_value: int | None = None) -> int:
    try:
        value = int(_env_str(name, str(default)).strip())
    except Exception:
        value = default
    if min_value is not None and value < min_value:
        value = min_value
    if max_value is not None and value > max_value:
        value = max_value
    return value


def _env_float(name: str, default: float, min_value: float | None = None, max_value: float | None = None) -> float:
    try:
        value = float(_env_str(name, str(default)).strip())
    except Exception:
        value = default
    if min_value is not None and value < min_value:
        value = min_value
    if max_value is not None and value > max_value:
        value = max_value
    return value


HOST = _env_str("HOST", "0.0.0.0")
PORT = _env_int("PORT", 28889, min_value=1, max_value=65535)

CLIENT_ID = _env_str("WARP_CLIENT_ID", "warp-app")
CLIENT_VERSION = _env_str("WARP_CLIENT_VERSION", "v0.2026.02.11.08.23.stable_02")
OS_CATEGORY = _env_str("WARP_OS_CATEGORY", "macOS")
OS_NAME = _env_str("WARP_OS_NAME", "macOS")
OS_VERSION = _env_str("WARP_OS_VERSION", "26.4")

TEXT_FIELD_NAMES = ("text", "prompt", "query", "content", "message", "input")
PATH_HINT_BONUS = ("conversation", "query", "input", "user", "request", "delta")

SYSTEM_STR = {"agent_output.text", "server_message_data", "USER_INITIATED", "agent_output", "text"}

# Strict mode for production-like envs: require explicit auth material.
STRICT_ENV = _env_bool("STRICT_ENV", False)

REFRESH_URL = _env_str(
    "WARP_REFRESH_URL",
    "https://app.warp.dev/proxy/token?key=AIzaSyBdy3O3S9hrdayLJxJ7mriBR4qgUaUygAs"
)
SECURETOKEN_URL = _env_str("WARP_SECURETOKEN_URL", "https://securetoken.googleapis.com/v1/token")

def get_api_token() -> str:
    return _env_str("API_TOKEN", "").strip()


def get_admin_token() -> str:
    return _env_str("ADMIN_TOKEN", "").strip()


def get_admin_auth_mode() -> str:
    mode = _env_str("WARP_ADMIN_AUTH_MODE", "token").strip().lower()
    if mode in {"off", "local", "token"}:
        return mode
    return "token"


def get_token_db_path() -> str | None:
    return _env_str("WARP_TOKEN_DB_PATH", "").strip() or None

WARP_COMPAT_SESSION_TTL = _env_int("WARP_COMPAT_SESSION_TTL", 1800, min_value=60, max_value=86400)
WARP_COMPAT_INIT_RETRIES = _env_int("WARP_COMPAT_INIT_RETRIES", 10, min_value=1, max_value=100)
WARP_COMPAT_INIT_DELAY = _env_float("WARP_COMPAT_INIT_DELAY", 0.5, min_value=0.0, max_value=30.0)
WARP_COMPAT_WARMUP_RETRIES = _env_int("WARP_COMPAT_WARMUP_RETRIES", 3, min_value=1, max_value=20)
WARP_COMPAT_WARMUP_DELAY = _env_float("WARP_COMPAT_WARMUP_DELAY", 1.5, min_value=0.0, max_value=30.0)
WARP_COMPAT_STARTUP_WARMUP = _env_bool("WARP_COMPAT_STARTUP_WARMUP", False)

WARP_TOKEN_REFRESH_RETRY_COUNT = _env_int("WARP_TOKEN_REFRESH_RETRY_COUNT", 3, min_value=1, max_value=10)
WARP_TOKEN_REFRESH_RETRY_BASE_DELAY_MS = _env_int("WARP_TOKEN_REFRESH_RETRY_BASE_DELAY_MS", 400, min_value=0, max_value=10000)
WARP_TOKEN_ERROR_COOLDOWN_SECONDS = _env_int("WARP_TOKEN_ERROR_COOLDOWN_SECONDS", 180, min_value=1, max_value=86400)

WARP_TOKEN_COOLDOWN_SECONDS = _env_int("WARP_TOKEN_COOLDOWN_SECONDS", 600, min_value=1, max_value=86400)
WARP_TOKEN_UNHEALTHY_FAILURE_THRESHOLD = _env_int("WARP_TOKEN_UNHEALTHY_FAILURE_THRESHOLD", 3, min_value=1, max_value=100)
WARP_REQUEST_RETRY_COUNT = _env_int("WARP_REQUEST_RETRY_COUNT", 3, min_value=1, max_value=10)
WARP_REQUEST_RETRY_BASE_DELAY_MS = _env_int("WARP_REQUEST_RETRY_BASE_DELAY_MS", 300, min_value=0, max_value=10000)

WARP_POOL_HEALTH_INTERVAL_SECONDS = _env_int("WARP_POOL_HEALTH_INTERVAL_SECONDS", 120, min_value=10, max_value=86400)
WARP_POOL_REFRESH_INTERVAL_SECONDS = _env_int("WARP_POOL_REFRESH_INTERVAL_SECONDS", WARP_POOL_HEALTH_INTERVAL_SECONDS, min_value=10, max_value=86400)
WARP_POOL_MONITOR_INTERVAL_SECONDS = _env_int("WARP_POOL_MONITOR_INTERVAL_SECONDS", WARP_POOL_REFRESH_INTERVAL_SECONDS, min_value=10, max_value=86400)
WARP_POOL_TOKEN_REFRESH_INTERVAL_SECONDS = _env_int("WARP_POOL_TOKEN_REFRESH_INTERVAL_SECONDS", 180, min_value=30, max_value=86400)
WARP_POOL_MONITOR_MAX_PARALLEL = _env_int("WARP_POOL_MONITOR_MAX_PARALLEL", 3, min_value=1, max_value=32)
WARP_POOL_QUOTA_RETRY_LEAD_SECONDS = _env_int("WARP_POOL_QUOTA_RETRY_LEAD_SECONDS", 300, min_value=30, max_value=3600)


def get_env_warp_jwt() -> str:
    # Keep dynamic read because runtime refresh writes back into process env.
    return _env_str("WARP_JWT", "").strip()


def strict_auth_config_ok() -> bool:
    if not STRICT_ENV:
        return True
    has_jwt = bool(get_env_warp_jwt())
    return has_jwt
