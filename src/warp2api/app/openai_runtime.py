#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""warp2api multi-protocol gateway runtime entrypoint."""

from __future__ import annotations

from warp2api.infrastructure.settings.settings import HOST, PORT
from .openai import gateway_app


def _resolve_port(cli_port: int | None = None) -> int:
    if cli_port is not None:
        return int(cli_port)
    return PORT


def run_gateway_server(port: int | None = None, reload: bool = False) -> None:
    import uvicorn
    resolved_port = _resolve_port(port)

    if reload:
        uvicorn.run(
            "warp2api.app.openai:gateway_app",
            host=HOST,
            port=resolved_port,
            log_level="info",
            reload=True,
            reload_dirs=[".", "src"],
        )
    else:
        uvicorn.run(
            gateway_app,
            host=HOST,
            port=resolved_port,
            log_level="info",
        )


# Backward compatibility for internal imports.
run_openai_server = run_gateway_server


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="warp2api 多协议网关服务器")
    parser.add_argument("--port", type=int, default=None, help="服务器监听端口 (默认: 从 PORT 或 28889)")
    parser.add_argument("--reload", action="store_true", help="启用热重载模式（代码修改自动重启）")
    args = parser.parse_args()
    run_gateway_server(port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
