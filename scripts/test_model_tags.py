#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import json
from dotenv import load_dotenv

from warp2api.infrastructure.auth.jwt_auth import get_valid_jwt
from warp2api.infrastructure.protobuf.minimal_request import send_minimal_warp_query

CANDIDATES = [
    "auto",
    "claude-4-sonnet",
    "claude-4.1-opus",
    "gemini-2.5-pro",
    "gemini-3-pro",
    "gpt-5",
]


async def main() -> None:
    load_dotenv(".env", override=False)
    jwt = await get_valid_jwt()
    rows = []
    for model_tag in CANDIDATES:
        result = await asyncio.to_thread(
            send_minimal_warp_query,
            "只回复:OK",
            jwt,
            20,
            model_tag,
            "v0.2026.01.14.08.15.stable_02",
            "15.7.2",
        )
        text = (result.get("text") or "").strip()
        ok = bool(result.get("ok")) and int(result.get("status_code") or 0) == 200 and bool(text)
        rows.append(
            {
                "model_tag": model_tag,
                "status_code": result.get("status_code"),
                "ok": ok,
                "text_preview": text[:20],
                "error_preview": (result.get("error") or "")[:100],
            }
        )
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
