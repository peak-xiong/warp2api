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

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8002"))
WARP_JWT = os.getenv("WARP_JWT")

CLIENT_ID = os.getenv("WARP_CLIENT_ID", "warp-app")
CLIENT_VERSION = os.getenv("WARP_CLIENT_VERSION", "v0.2026.02.11.08.23.stable_02")
OS_CATEGORY = os.getenv("WARP_OS_CATEGORY", "macOS")
OS_NAME = os.getenv("WARP_OS_NAME", "macOS")
OS_VERSION = os.getenv("WARP_OS_VERSION", "26.4")

TEXT_FIELD_NAMES = ("text", "prompt", "query", "content", "message", "input")
PATH_HINT_BONUS = ("conversation", "query", "input", "user", "request", "delta")

SYSTEM_STR = {"agent_output.text", "server_message_data", "USER_INITIATED", "agent_output", "text"}

# Strict mode for production-like envs: require explicit auth material.
STRICT_ENV = str(os.getenv("STRICT_ENV", "false")).strip().lower() in {"1", "true", "yes", "on"}

# JWT refresh configuration
REFRESH_TOKEN_B64 = (os.getenv("WARP_REFRESH_TOKEN_B64") or "").strip()
REFRESH_URL = os.getenv(
    "WARP_REFRESH_URL",
    "https://app.warp.dev/proxy/token?key=AIzaSyBdy3O3S9hrdayLJxJ7mriBR4qgUaUygAs",
)
SECURETOKEN_URL = os.getenv("WARP_SECURETOKEN_URL", "https://securetoken.googleapis.com/v1/token")


def strict_auth_config_ok() -> bool:
    if not STRICT_ENV:
        return True
    has_jwt = bool((os.getenv("WARP_JWT") or "").strip())
    has_refresh = bool((os.getenv("WARP_REFRESH_TOKEN") or "").strip())
    has_refresh_pool = bool((os.getenv("WARP_REFRESH_TOKENS") or "").strip())
    has_refresh_b64 = bool((os.getenv("WARP_REFRESH_TOKEN_B64") or "").strip())
    return has_jwt or has_refresh or has_refresh_pool or has_refresh_b64
