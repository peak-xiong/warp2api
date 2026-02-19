#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import asyncio
import os
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv

from warp2api.application.services.chat_gateway_support import packet_template
from warp2api.infrastructure.protobuf.utils import dict_to_protobuf_bytes
from warp2api.application.services.token_rotation_service import send_protobuf_with_rotation


def _mask(v: str) -> str:
    if not v:
        return ""
    if len(v) <= 10:
        return "***"
    return f"{v[:4]}...{v[-4:]}"


def _print_env_diag() -> None:
    print("=== Env Diagnostics ===")
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "WARP_TRUST_ENV"):
        val = os.getenv(k, "")
        if k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY") and val:
            print(f"{k}={_mask(val)}")
        else:
            print(f"{k}={val}")
    print(f"WARP_REFRESH_TOKEN={'set' if os.getenv('WARP_REFRESH_TOKEN') else 'unset'}")
    print(f"WARP_JWT={'set' if os.getenv('WARP_JWT') else 'unset'}")


async def run_once(prompt: str) -> int:
    packet = packet_template()
    task_id = str(uuid.uuid4())
    packet["task_context"]["active_task_id"] = task_id
    packet["input"]["user_inputs"]["inputs"] = [{"user_query": {"query": prompt}}]

    pb = dict_to_protobuf_bytes(packet, "warp.multi_agent.v1.Request")
    print(f"request_task_id={task_id}")
    print(f"request_bytes={len(pb)}")

    result = await send_protobuf_with_rotation(
        protobuf_bytes=pb,
        timeout_seconds=90,
    )

    print("=== Warp Result ===")
    print(f"conversation_id={result.get('conversation_id')}")
    print(f"task_id={result.get('task_id')}")
    events = result.get("parsed_events") or []
    print(f"events_count={len(events)}")

    if not result.get("ok"):
        print(f"error=HTTP {result.get('status_code')} {result.get('error')}")
        return 2

    text = str(result.get("text") or "")
    print("response_preview:")
    print(text[:1200] if text else "<empty>")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Minimal Warp multi-agent request demo")
    parser.add_argument("--prompt", default="warmup", help="Prompt to send")
    parser.add_argument(
        "--env-file",
        default=".env",
        help="Path to .env file (default: .env)",
    )
    args = parser.parse_args()

    env_file = Path(args.env_file)
    if env_file.exists():
        load_dotenv(env_file, override=True)

    # Default to direct connection; set WARP_TRUST_ENV=1 only when you really want proxy from env.
    os.environ.setdefault("WARP_TRUST_ENV", "0")

    _print_env_diag()

    try:
        return asyncio.run(run_once(args.prompt))
    except KeyboardInterrupt:
        return 130
    except Exception as e:
        print(f"fatal_error={type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
