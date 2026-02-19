from __future__ import annotations

import argparse

from .bridge_runtime import run_server
from .openai_runtime import run_openai_server


def main() -> None:
    parser = argparse.ArgumentParser(description="warp2api unified launcher")
    parser.add_argument("--mode", choices=["bridge", "openai"], default="bridge", help="Service mode")
    parser.add_argument("--port", type=int, default=None, help="Listen port")
    parser.add_argument("--reload", action="store_true", help="Enable autoreload")
    args = parser.parse_args()

    if args.mode == "bridge":
        run_server(port=args.port or 28888, reload=args.reload)
    else:
        run_openai_server(port=args.port or 28889, reload=args.reload)
