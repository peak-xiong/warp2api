from __future__ import annotations

import json
from typing import Any, Dict

import httpx

from warp2api.infrastructure.settings.settings import CLIENT_ID, CLIENT_VERSION, OS_CATEGORY, OS_NAME, OS_VERSION
from warp2api.infrastructure.transport.warp_transport import get_httpx_client


async def get_request_limit(access_token: str) -> Dict[str, Any]:
    token = str(access_token or "").strip()
    if not token:
        raise ValueError("missing access token")

    query = """
query GetRequestLimitInfo($requestContext: RequestContext!) {
  user(requestContext: $requestContext) {
    __typename
    ... on UserOutput {
      user {
        requestLimitInfo {
          isUnlimited
          nextRefreshTime
          requestLimit
          requestsUsedSinceLastRefresh
          requestLimitRefreshDuration
        }
      }
    }
    ... on UserFacingError {
      error {
        __typename
        message
      }
    }
  }
}
""".strip()

    payload = {
        "operationName": "GetRequestLimitInfo",
        "variables": {
            "requestContext": {
                "clientContext": {"version": CLIENT_VERSION},
                "osContext": {
                    "category": OS_CATEGORY,
                    "linuxKernelVersion": None,
                    "name": OS_NAME,
                    "version": OS_VERSION,
                },
            }
        },
        "query": query,
    }

    client = get_httpx_client()
    resp = await client.post(
        "https://app.warp.dev/graphql/v2?op=GetRequestLimitInfo",
        json=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "x-warp-client-id": CLIENT_ID or "warp-app",
            "x-warp-client-version": CLIENT_VERSION,
            "x-warp-os-category": OS_CATEGORY,
            "x-warp-os-name": OS_NAME,
            "x-warp-os-version": OS_VERSION,
        },
        timeout=httpx.Timeout(20.0),
    )

    if resp.status_code < 200 or resp.status_code >= 300:
        snippet = resp.text[:400].replace("\n", " ")
        raise RuntimeError(f"warp quota http {resp.status_code}: {snippet}")

    try:
        data = resp.json()
    except Exception as exc:
        raise RuntimeError(f"invalid quota json: {exc}") from exc

    if data.get("errors"):
        msg = str(data["errors"][0].get("message") or "graphql error")
        raise RuntimeError(f"warp quota graphql error: {msg}")

    user_node = ((data.get("data") or {}).get("user") or {})
    typename = str(user_node.get("__typename") or "")
    if typename == "UserFacingError":
        msg = (((user_node.get("error") or {}).get("message")) or "user error")
        raise RuntimeError(f"warp quota user error: {msg}")
    if typename != "UserOutput":
        raise RuntimeError(f"warp quota unexpected typename: {typename or 'unknown'}")

    limit_info = ((((user_node.get("user") or {}).get("requestLimitInfo")) or {}))
    request_limit = int(limit_info.get("requestLimit") or 0)
    used = int(limit_info.get("requestsUsedSinceLastRefresh") or 0)
    is_unlimited = bool(limit_info.get("isUnlimited") or False)
    if is_unlimited:
        request_limit = -1
        used = 0
    remaining = request_limit - used if request_limit >= 0 else -1
    return {
        "request_limit": request_limit,
        "requests_used": used,
        "requests_remaining": remaining,
        "is_unlimited": is_unlimited,
        "next_refresh_time": limit_info.get("nextRefreshTime"),
        "refresh_duration": limit_info.get("requestLimitRefreshDuration") or "WEEKLY",
    }

