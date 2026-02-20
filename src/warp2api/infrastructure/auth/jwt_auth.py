#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JWT Authentication for Warp API

Handles JWT token management, refresh, and validation.
Integrates functionality from refresh_jwt.py.
"""
import base64
import json
import os
import time
from typing import Optional, List
import httpx

from warp2api.infrastructure.settings.settings import (
    REFRESH_URL,
    SECURETOKEN_URL,
    CLIENT_VERSION,
    OS_CATEGORY,
    OS_NAME,
    OS_VERSION,
    STRICT_ENV,
    get_env_warp_jwt,
)
from warp2api.observability.logging import logger


def decode_jwt_payload(token: str) -> dict:
    """Decode JWT payload to check expiration"""
    try:
        parts = token.split('.')
        if len(parts) != 3:
            return {}
        payload_b64 = parts[1]
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += '=' * padding
        payload_bytes = base64.urlsafe_b64decode(payload_b64)
        payload = json.loads(payload_bytes.decode('utf-8'))
        return payload
    except Exception as e:
        logger.debug(f"Error decoding JWT: {e}")
        return {}


def is_token_expired(token: str, buffer_minutes: int = 5) -> bool:
    payload = decode_jwt_payload(token)
    if not payload or 'exp' not in payload:
        return True
    expiry_time = payload['exp']
    current_time = time.time()
    buffer_time = buffer_minutes * 60
    return (expiry_time - current_time) <= buffer_time


def _token_value(token_data: dict) -> str:
    if not isinstance(token_data, dict):
        return ""
    return str(token_data.get("access_token") or token_data.get("id_token") or "").strip()


def _split_refresh_tokens(raw: str) -> List[str]:
    if not raw:
        return []
    # Supports comma/newline/semicolon separators.
    parts = []
    for item in raw.replace("\n", ",").replace(";", ",").split(","):
        t = item.strip().strip("'").strip('"')
        if t:
            parts.append(t)
    return parts


def get_refresh_token_candidates(refresh_token_override: Optional[str] = None) -> List[str]:
    """Return unique refresh-token candidates in priority order.

    Unified mode: token pool should pass refresh_token_override explicitly.
    """
    ordered: List[str] = []

    def _add(token: Optional[str]) -> None:
        t = (token or "").strip()
        if t and t not in ordered:
            ordered.append(t)

    _add(refresh_token_override)
    return ordered


def _extract_google_api_key_from_refresh_url() -> str:
    try:
        # REFRESH_URL like: https://app.warp.dev/proxy/token?key=API_KEY
        from urllib.parse import urlparse, parse_qs as _parse_qs
        parsed = urlparse(REFRESH_URL)
        qs = _parse_qs(parsed.query)
        key = qs.get("key", [""])[0]
        return key
    except Exception:
        return ""


async def _refresh_via_securetoken(refresh_token: str) -> dict:
    key = _extract_google_api_key_from_refresh_url() or "AIzaSyBdy3O3S9hrdayLJxJ7mriBR4qgUaUygAs"
    url = SECURETOKEN_URL
    if "?" not in url:
        url = f"{url}?key={key}"
    elif "key=" not in url:
        url = f"{url}&key={key}"
    headers = {
        "content-type": "application/json",
        "accept": "*/*",
        "accept-encoding": "gzip, br",
        "x-warp-client-version": CLIENT_VERSION,
        "x-warp-os-category": OS_CATEGORY,
        "x-warp-os-name": OS_NAME,
        "x-warp-os-version": OS_VERSION,
    }
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0), trust_env=False) as client:
        resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code != 200:
            raise RuntimeError(f"securetoken refresh failed: HTTP {resp.status_code} {resp.text[:200]}")
        data = resp.json()
        token = str(data.get("id_token") or "").strip()
        if not token:
            raise RuntimeError(f"securetoken refresh missing id_token: {data}")
        return {
            "access_token": token,
            "refresh_token": data.get("refresh_token") or refresh_token,
            "expires_in": data.get("expires_in"),
            "source": "securetoken",
        }


async def refresh_jwt_token(refresh_token_override: Optional[str] = None) -> dict:
    """Refresh JWT using refresh token.

    Priority: explicit refresh token only.
    Refresh flow priority: securetoken endpoint.
    """
    logger.info("Refreshing JWT token...")
    refresh_candidates = get_refresh_token_candidates(refresh_token_override)
    if not refresh_candidates:
        msg = "No refresh token available for JWT refresh (token pool account not configured)"
        if STRICT_ENV:
            logger.error("%s (STRICT_ENV enabled)", msg)
            raise RuntimeError(msg)
        logger.error(msg)
        return {"error": msg}
    last_error: Optional[str] = None
    for idx, refresh_token in enumerate(refresh_candidates, start=1):
        try:
            token_data = await _refresh_via_securetoken(refresh_token)
            token_data["used_refresh_token"] = refresh_token
            logger.info("Token refresh successful via securetoken (candidate %s/%s)", idx, len(refresh_candidates))
            return token_data
        except Exception as e:
            last_error = f"securetoken: {e}"
            logger.warning("Securetoken refresh failed for candidate %s/%s: %s", idx, len(refresh_candidates), e)
    logger.error("Error refreshing token with all candidates: %s", last_error or "unknown")
    return {"error": last_error or "unknown"}


def update_env_file(new_jwt: str) -> bool:
    try:
        os.environ["WARP_JWT"] = new_jwt
        logger.info("Updated in-memory JWT token")
        return True
    except Exception as e:
        logger.error(f"Error updating JWT token: {e}")
        return False


async def check_and_refresh_token() -> bool:
    current_jwt = get_env_warp_jwt()
    if not current_jwt:
        logger.warning("No JWT token found in environment")
        token_data = await refresh_jwt_token()
        if token_data:
            new_jwt = _token_value(token_data)
            if not new_jwt:
                return False
            ok = update_env_file(new_jwt)
            return ok
        return False
    logger.debug("Checking current JWT token expiration...")
    if is_token_expired(current_jwt, buffer_minutes=15):
        logger.info("JWT token is expired or expiring soon, refreshing...")
        token_data = await refresh_jwt_token()
        if token_data:
            new_jwt = _token_value(token_data)
            if not new_jwt:
                logger.warning("Refresh response does not contain access token")
                return False
            if not is_token_expired(new_jwt, buffer_minutes=0):
                logger.info("New token is valid")
                ok = update_env_file(new_jwt)
                return ok
            else:
                logger.warning("New token appears to be invalid or expired")
                return False
        else:
            logger.error("Failed to get new token from refresh")
            return False
    else:
        payload = decode_jwt_payload(current_jwt)
        if payload and 'exp' in payload:
            expiry_time = payload['exp']
            time_left = expiry_time - time.time()
            hours_left = time_left / 3600
            logger.debug(f"Current token is still valid ({hours_left:.1f} hours remaining)")
        else:
            logger.debug("Current token appears valid")
        return True


async def get_valid_jwt() -> str:
    from dotenv import load_dotenv as _load
    _load(override=True)
    jwt = get_env_warp_jwt()
    if not jwt:
        logger.info("No JWT token found, attempting to refresh...")
        if await check_and_refresh_token():
            _load(override=True)
            jwt = get_env_warp_jwt()
        if not jwt:
            raise RuntimeError("WARP_JWT is not set and refresh failed")
    if is_token_expired(jwt, buffer_minutes=2):
        logger.info("JWT token is expired or expiring soon, attempting to refresh...")
        if await check_and_refresh_token():
            _load(override=True)
            jwt = get_env_warp_jwt()
            if not jwt or is_token_expired(jwt, buffer_minutes=0):
                logger.warning("Warning: New token has short expiry but proceeding anyway")
        else:
            logger.warning("Warning: JWT token refresh failed, trying to use existing token")
    return jwt


def get_jwt_token() -> str:
    return get_env_warp_jwt()


async def refresh_jwt_if_needed() -> bool:
    try:
        return await check_and_refresh_token()
    except Exception as e:
        logger.error(f"JWT refresh failed: {e}")
        return False


# ============ Anonymous token acquisition (quota refresh) ============

_ANON_GQL_URL = "https://app.warp.dev/graphql/v2?op=CreateAnonymousUser"
_IDENTITY_TOOLKIT_BASE = "https://identitytoolkit.googleapis.com/v1/accounts:signInWithCustomToken"


async def _create_anonymous_user() -> dict:
    headers = {
        "accept-encoding": "gzip, br",
        "content-type": "application/json",
        "x-warp-client-version": CLIENT_VERSION,
        "x-warp-os-category": OS_CATEGORY,
        "x-warp-os-name": OS_NAME,
        "x-warp-os-version": OS_VERSION,
    }
    # GraphQL payload per anonymous.MD
    query = (
        "mutation CreateAnonymousUser($input: CreateAnonymousUserInput!, $requestContext: RequestContext!) {\n"
        "  createAnonymousUser(input: $input, requestContext: $requestContext) {\n"
        "    __typename\n"
        "    ... on CreateAnonymousUserOutput {\n"
        "      expiresAt\n"
        "      anonymousUserType\n"
        "      firebaseUid\n"
        "      idToken\n"
        "      isInviteValid\n"
        "      responseContext { serverVersion }\n"
        "    }\n"
        "    ... on UserFacingError {\n"
        "      error { __typename message }\n"
        "      responseContext { serverVersion }\n"
        "    }\n"
        "  }\n"
        "}\n"
    )
    variables = {
        "input": {
            "anonymousUserType": "NATIVE_CLIENT_ANONYMOUS_USER_FEATURE_GATED",
            "expirationType": "NO_EXPIRATION",
            "referralCode": None
        },
        "requestContext": {
            "clientContext": {"version": CLIENT_VERSION},
            "osContext": {
                "category": OS_CATEGORY,
                "linuxKernelVersion": None,
                "name": OS_NAME,
                "version": OS_VERSION,
            }
        }
    }
    body = {"query": query, "variables": variables, "operationName": "CreateAnonymousUser"}
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0), trust_env=False) as client:
        resp = await client.post(_ANON_GQL_URL, headers=headers, json=body)
        if resp.status_code != 200:
            raise RuntimeError(f"CreateAnonymousUser failed: HTTP {resp.status_code} {resp.text[:200]}")
        data = resp.json()
        return data


async def _exchange_id_token_for_refresh_token(id_token: str) -> dict:
    key = _extract_google_api_key_from_refresh_url()
    url = f"{_IDENTITY_TOOLKIT_BASE}?key={key}" if key else f"{_IDENTITY_TOOLKIT_BASE}?key=AIzaSyBdy3O3S9hrdayLJxJ7mriBR4qgUaUygAs"
    headers = {
        "accept-encoding": "gzip, br",
        "content-type": "application/x-www-form-urlencoded",
        "x-warp-client-version": CLIENT_VERSION,
        "x-warp-os-category": OS_CATEGORY,
        "x-warp-os-name": OS_NAME,
        "x-warp-os-version": OS_VERSION,
    }
    form = {
        "returnSecureToken": "true",
        "token": id_token,
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0), trust_env=False) as client:
        resp = await client.post(url, headers=headers, data=form)
        if resp.status_code != 200:
            raise RuntimeError(f"signInWithCustomToken failed: HTTP {resp.status_code} {resp.text[:200]}")
        return resp.json()


async def acquire_anonymous_access_token() -> str:
    """Acquire a new anonymous access token (quota refresh) and persist to .env.

    Returns the new access token string. Raises on failure.
    """
    logger.info("Acquiring anonymous access token via GraphQL + Identity Toolkit…")
    data = await _create_anonymous_user()
    id_token = None
    try:
        id_token = data["data"]["createAnonymousUser"].get("idToken")
    except Exception:
        pass
    if not id_token:
        raise RuntimeError(f"CreateAnonymousUser did not return idToken: {data}")

    signin = await _exchange_id_token_for_refresh_token(id_token)
    refresh_token = signin.get("refreshToken")
    if not refresh_token:
        raise RuntimeError(f"signInWithCustomToken did not return refreshToken: {signin}")

    # Persist refresh token for future time-based refreshes
    update_env_refresh_token(refresh_token)

    # Exchange refresh token to usable JWT (id_token/access_token)
    token_data = await refresh_jwt_token(refresh_token_override=refresh_token)
    access = _token_value(token_data)
    if not access:
        raise RuntimeError(f"Acquire access token failed from refresh flow: {token_data}")
    update_env_file(access)
    return access


def print_token_info():
    current_jwt = get_env_warp_jwt()
    if not current_jwt:
        logger.info("No JWT token found")
        return
    payload = decode_jwt_payload(current_jwt)
    if not payload:
        logger.info("Cannot decode JWT token")
        return
    logger.info("=== JWT Token Information ===")
    if 'email' in payload:
        logger.info(f"Email: {payload['email']}")
    if 'user_id' in payload:
        logger.info(f"User ID: {payload['user_id']}") 
