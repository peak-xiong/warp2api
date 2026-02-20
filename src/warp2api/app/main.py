from __future__ import annotations

import argparse

from .openai_runtime import run_gateway_server


def main() -> None:
    parser = argparse.ArgumentParser(description="warp2api unified launcher")
    parser.add_argument("--mode", choices=["openai"], default="openai", help="Service mode")
    parser.add_argument("--port", type=int, default=None, help="Listen port")
    parser.add_argument("--reload", action="store_true", help="Enable autoreload")
    args = parser.parse_args()

    run_gateway_server(port=args.port, reload=args.reload)
