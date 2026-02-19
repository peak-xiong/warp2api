#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenAI Chat Completions compatible server (system-prompt flavored)

Startup entrypoint that exposes the modular app implemented in src/warp2api.
"""

from __future__ import annotations

import asyncio
import os

from .openai import openai_app


def run_openai_server(port: int = 28889, reload: bool = False) -> None:
    import uvicorn

    # Refresh JWT on startup before running the server
    try:
        from warp2api.infrastructure.auth.jwt_auth import refresh_jwt_if_needed as _refresh_jwt
        asyncio.run(_refresh_jwt())
    except Exception:
        pass

    if reload:
        uvicorn.run(
            "warp2api.app.openai:openai_app",
            host=os.getenv("HOST", "127.0.0.1"),
            port=port,
            log_level="info",
            reload=True,
            reload_dirs=[".", "src"],
        )
    else:
        uvicorn.run(
            openai_app,
            host=os.getenv("HOST", "127.0.0.1"),
            port=port,
            log_level="info",
        )


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="OpenAI兼容API服务器")
    parser.add_argument("--port", type=int, default=28889, help="服务器监听端口 (默认: 28889)")
    parser.add_argument("--reload", action="store_true", help="启用热重载模式（代码修改自动重启）")
    args = parser.parse_args()
    run_openai_server(port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
