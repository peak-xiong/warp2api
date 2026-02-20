#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from typing import Any

import httpx


def _classify(status_code: int, body: Any) -> str:
    raw = ""
    if isinstance(body, dict):
        raw = json.dumps(body, ensure_ascii=False)
    else:
        raw = str(body or "")
    low = raw.lower()
    if status_code == 200:
        return "ok"
    if "not allowed for your account" in low:
        return "not_allowed"
    if "no remaining quota" in low or "no ai requests remaining" in low:
        return "quota_exhausted"
    if "unsupported model" in low or "model not found" in low:
        return "unsupported_model"
    return f"http_{status_code}"


def _load_models(client: httpx.Client, base_url: str, api_token: str) -> list[str]:
    headers = {"Authorization": f"Bearer {api_token}"}
    r = client.get(f"{base_url.rstrip('/')}/v1/models", headers=headers)
    r.raise_for_status()
    data = r.json()
    models = []
    for item in (data.get("data") or []):
        model_id = str(item.get("id") or "").strip()
        if model_id:
            models.append(model_id)
    return models


def main() -> int:
    p = argparse.ArgumentParser(description="Probe model availability via remote /v1/messages endpoint.")
    p.add_argument("--endpoint", required=True, help="Gateway base URL, e.g. https://warp.example.com")
    p.add_argument("--api-token", required=True, help="Gateway API token")
    p.add_argument(
        "--models",
        default="auto,claude-4.6-opus,claude-4.5-haiku,gpt-5,gemini-2.5-pro",
        help="Comma-separated model ids; ignored when --from-server-models is set",
    )
    p.add_argument("--from-server-models", action="store_true", help="Load model ids from GET /v1/models")
    p.add_argument("--timeout", type=float, default=30.0, help="Request timeout in seconds")
    args = p.parse_args()

    base_url = args.endpoint.rstrip("/")
    headers = {
        "Authorization": f"Bearer {args.api_token}",
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    with httpx.Client(timeout=args.timeout, verify=True, follow_redirects=True) as client:
        if args.from_server_models:
            model_ids = _load_models(client, base_url, args.api_token)
        else:
            model_ids = [m.strip() for m in args.models.split(",") if m.strip()]

        print(f"endpoint={base_url}")
        print(f"models={len(model_ids)}")
        for model in model_ids:
            payload = {
                "model": model,
                "max_tokens": 32,
                "messages": [{"role": "user", "content": "ping"}],
                "stream": False,
            }
            try:
                resp = client.post(f"{base_url}/v1/messages", headers=headers, json=payload)
                body: Any
                try:
                    body = resp.json()
                except Exception:
                    body = resp.text[:400]
                status = _classify(resp.status_code, body)
                print(f"{model}\t{status}\tHTTP {resp.status_code}")
            except Exception as e:
                print(f"{model}\terror\t{e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

