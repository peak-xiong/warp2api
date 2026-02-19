from __future__ import annotations

import argparse

import uvicorn
from fastapi import FastAPI

from .bridge_app import create_app
from .bridge_bootstrap import startup_tasks


def run_server(port: int = 28888, reload: bool = False) -> None:
    if reload:
        uvicorn.run(
            "warp2api.app.bridge_runtime:create_app",
            factory=True,
            host="0.0.0.0",
            port=port,
            log_level="info",
            access_log=True,
            reload=True,
            reload_dirs=[".", "src"],
        )
        return

    app = create_app()
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info",
        access_log=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Warp Protobuf编解码服务器")
    parser.add_argument("--port", type=int, default=28888, help="服务器监听端口 (默认: 28888)")
    parser.add_argument("--reload", action="store_true", help="启用热重载模式（代码修改自动重启）")
    args = parser.parse_args()
    run_server(port=args.port, reload=args.reload)


__all__ = ["create_app", "run_server", "startup_tasks", "main", "FastAPI"]


if __name__ == "__main__":
    main()
