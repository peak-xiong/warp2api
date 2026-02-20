from __future__ import annotations

from fastapi import HTTPException, Request, status

from warp2api.infrastructure.settings.settings import get_admin_auth_mode, get_admin_token


def _get_admin_token() -> str:
    return get_admin_token()


def _auth_mode() -> str:
    mode = get_admin_auth_mode()
    if mode in {"off", "local", "token"}:
        return mode
    return "token"


def _is_local_request(request: Request) -> bool:
    host = ""
    try:
        if request.client and request.client.host:
            host = str(request.client.host)
    except Exception:
        host = ""
    return host in {"127.0.0.1", "::1", "localhost", "testclient"}


async def require_admin_auth(request: Request) -> None:
    mode = _auth_mode()
    if mode == "off":
        return
    if mode == "local" and _is_local_request(request):
        return

    expected = _get_admin_token()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ADMIN_TOKEN is not configured (or set WARP_ADMIN_AUTH_MODE=local/off)",
        )

    auth = request.headers.get("authorization") or request.headers.get("Authorization") or ""
    x_admin = request.headers.get("x-admin-token") or ""

    bearer = ""
    if auth.startswith("Bearer "):
        bearer = auth[7:].strip()

    if bearer == expected or x_admin == expected:
        return

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid admin token",
        headers={"WWW-Authenticate": "Bearer"},
    )
