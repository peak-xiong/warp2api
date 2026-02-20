#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import httpx


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _convert_accounts(raw: dict[str, Any]) -> dict[str, Any]:
    src_accounts = raw.get("accounts") if isinstance(raw, dict) else []
    if not isinstance(src_accounts, list):
        src_accounts = []

    out_accounts: list[dict[str, Any]] = []
    for item in src_accounts:
        if not isinstance(item, dict):
            continue
        refresh_token = str(item.get("refreshToken") or "").strip()
        if not refresh_token:
            continue
        out_accounts.append(
            {
                "refresh_token": refresh_token,
                "email": item.get("email") or None,
                "api_key": item.get("apiKey") or None,
                "id_token": item.get("idToken") or None,
                "total_limit": item.get("quota"),
                "used_limit": item.get("used"),
            }
        )
    return {"accounts": out_accounts}


def _post_import(endpoint: str, payload: dict[str, Any], admin_token: str, timeout: float) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if admin_token:
        headers["Authorization"] = f"Bearer {admin_token}"
    with httpx.Client(timeout=timeout, verify=True, follow_redirects=True) as client:
        resp = client.post(endpoint, headers=headers, json=payload)
    if resp.status_code >= 400:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:500]}")
    return resp.json()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert WarpManagerPro accounts.json and import to warp2api admin API."
    )
    parser.add_argument(
        "--input",
        default="/Users/xiongfeng/Library/Application Support/WarpManagerPro/accounts.json",
        help="Path to WarpManagerPro accounts.json",
    )
    parser.add_argument(
        "--endpoint",
        default="http://127.0.0.1:28889/admin/api/tokens/batch-import",
        help="warp2api admin batch-import endpoint",
    )
    parser.add_argument(
        "--admin-token",
        default="",
        help="ADMIN_TOKEN value (omit when auth mode is off/local)",
    )
    parser.add_argument(
        "--out",
        default="",
        help="Optional path to write converted payload JSON",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="HTTP timeout seconds",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only convert and print summary, do not POST",
    )
    args = parser.parse_args()

    input_path = Path(args.input).expanduser()
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    raw = _load_json(input_path)
    payload = _convert_accounts(raw)
    count = len(payload["accounts"])
    print(f"source: {input_path}")
    print(f"converted accounts: {count}")

    if args.out:
        out_path = Path(args.out).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"written: {out_path}")

    if args.dry_run:
        print("dry-run mode, skip POST")
        return 0

    result = _post_import(
        endpoint=args.endpoint,
        payload=payload,
        admin_token=str(args.admin_token or "").strip(),
        timeout=args.timeout,
    )
    print("import result:")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
