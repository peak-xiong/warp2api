from __future__ import annotations

import asyncio
import re
from typing import Any, Dict

from warp2api.domain.protocols.token_repository import TokenRepositoryProtocol
from warp2api.infrastructure.auth.jwt_auth import refresh_jwt_token
from warp2api.infrastructure.settings.settings import (
    WARP_TOKEN_ERROR_COOLDOWN_SECONDS,
    WARP_TOKEN_REFRESH_RETRY_BASE_DELAY_MS,
    WARP_TOKEN_REFRESH_RETRY_COUNT,
)
from warp2api.infrastructure.transport.warp_quota import get_request_limit
from warp2api.infrastructure.utils.datetime import future_iso, utcnow_iso, utcnow_timestamp

_REFRESH_RETRY_COUNT = WARP_TOKEN_REFRESH_RETRY_COUNT
_REFRESH_RETRY_BASE_DELAY_MS = WARP_TOKEN_REFRESH_RETRY_BASE_DELAY_MS
_REFRESH_ERROR_COOLDOWN_SECONDS = WARP_TOKEN_ERROR_COOLDOWN_SECONDS

_utcnow_iso = utcnow_iso
_future_iso = future_iso


class TokenRefreshService:
    """Handles token refresh, quota fetching, and health-check logic."""

    def __init__(self, repo: TokenRepositoryProtocol) -> None:
        self.repo = repo

    # ------------------------------------------------------------------
    # Quota helpers (static)
    # ------------------------------------------------------------------

    @staticmethod
    def status_by_quota(quota_data: Dict[str, Any]) -> str:
        if not quota_data:
            return "active"
        q_limit = int(quota_data.get("request_limit") or 0)
        q_used = int(quota_data.get("requests_used") or 0)
        q_unlimited = bool(quota_data.get("is_unlimited") or False)
        if (not q_unlimited) and q_limit >= 0 and q_used >= q_limit:
            return "quota_exhausted"
        return "active"

    @staticmethod
    def quota_update_fields(quota_data: Dict[str, Any], now_iso: str) -> Dict[str, Any]:
        if not quota_data:
            return {}
        return {
            "total_limit": int(quota_data.get("request_limit") or 0),
            "used_limit": int(quota_data.get("requests_used") or 0),
            "quota_limit": int(quota_data.get("request_limit") or 0),
            "quota_used": int(quota_data.get("requests_used") or 0),
            "quota_remaining": int(quota_data.get("requests_remaining") or 0),
            "quota_is_unlimited": bool(quota_data.get("is_unlimited") or False),
            "quota_next_refresh_time": str(quota_data.get("next_refresh_time") or ""),
            "quota_refresh_duration": str(quota_data.get("refresh_duration") or ""),
            "quota_updated_at": now_iso,
        }

    # ------------------------------------------------------------------
    # Error classification
    # ------------------------------------------------------------------

    @staticmethod
    def is_hard_invalid_refresh_error(error_message: str) -> bool:
        msg = (error_message or "").lower()
        return (
            "invalid_refresh_token" in msg
            or "invalid_grant" in msg
            or "refresh token is invalid" in msg
        )

    @staticmethod
    def parse_refresh_error(raw_error: str) -> Dict[str, str]:
        raw = (raw_error or "").strip()
        if not raw:
            return {"code": "refresh_failed", "message": "refresh failed"}

        upper_raw = raw.upper()
        if "INVALID_REFRESH_TOKEN" in upper_raw:
            return {"code": "invalid_refresh_token", "message": "INVALID_REFRESH_TOKEN"}
        if "INVALID_GRANT" in upper_raw:
            return {"code": "invalid_grant", "message": "INVALID_GRANT"}

        message_match = re.search(
            r'"message"\s*:\s*"([^"]+)"', raw, flags=re.IGNORECASE)
        status_match = re.search(
            r'"status"\s*:\s*"([^"]+)"', raw, flags=re.IGNORECASE)
        code_match = re.search(r'"code"\s*:\s*(\d+)', raw, flags=re.IGNORECASE)

        parsed_message = (message_match.group(1).strip()
                          if message_match else "").strip()
        parsed_status = (status_match.group(1).strip()
                         if status_match else "").strip()
        parsed_http_code = (code_match.group(1).strip()
                            if code_match else "").strip()

        if parsed_message:
            code = parsed_message.lower()
            if parsed_status:
                msg = f"{parsed_message} ({parsed_status})"
            else:
                msg = parsed_message
            if parsed_http_code:
                msg = f"{msg}, HTTP {parsed_http_code}"
            return {"code": code[:64], "message": msg[:240]}

        return {"code": "refresh_failed", "message": raw[:240]}

    # ------------------------------------------------------------------
    # Core refresh flow
    # ------------------------------------------------------------------

    async def _refresh_with_retry(self, refresh_token: str) -> Dict[str, Any]:
        last_error = ""
        for i in range(_REFRESH_RETRY_COUNT):
            try:
                token_data = await refresh_jwt_token(refresh_token_override=refresh_token)
            except Exception as exc:
                token_data = {}
                last_error = str(exc)

            access = str(token_data.get("access_token")
                         or token_data.get("id_token") or "").strip()
            if access:
                if i > 0:
                    token_data["retry_count"] = i + 1
                return token_data

            err = str(token_data.get("error") or "").strip()
            if err:
                last_error = err
            if not last_error:
                last_error = "refresh returned empty access token"

            if i < _REFRESH_RETRY_COUNT - 1:
                delay = (_REFRESH_RETRY_BASE_DELAY_MS * (i + 1)) / 1000.0
                if delay > 0:
                    await asyncio.sleep(delay)

        return {"error": last_error}

    async def refresh_token(self, token_id: int, actor: str) -> Dict[str, Any]:
        refresh_token = self.repo.get_refresh_token(token_id)
        if not refresh_token:
            raise ValueError("token not found")

        now = _utcnow_iso()
        now_ts = utcnow_timestamp()
        token_data = await self._refresh_with_retry(refresh_token)
        new_refresh = str(token_data.get("refresh_token")
                          or refresh_token).strip()
        access = str(token_data.get("access_token")
                     or token_data.get("id_token") or "").strip()

        if access:
            quota_data: Dict[str, Any] = {}
            try:
                quota_data = await get_request_limit(access)
            except Exception:
                quota_data = {}
            status_by_quota = self.status_by_quota(quota_data)
            quota_fields = self.quota_update_fields(quota_data, now)

            existing_id = self.repo.find_token_id_by_refresh_token(new_refresh)
            if existing_id is not None and int(existing_id) != int(token_id):
                self.repo.update_token(
                    int(existing_id),
                    status=status_by_quota,
                    error_count=0,
                    last_error_code="",
                    last_error_message="",
                    last_success_at=now,
                    last_check_at=now,
                    **quota_fields,
                )
                self.repo.upsert_health_snapshot(
                    token_id=int(existing_id),
                    healthy=True,
                    last_checked_at=now_ts,
                    last_success_at=now_ts,
                    last_error="",
                    consecutive_failures=0,
                    latency_ms=0,
                )
                self.repo.delete_token(token_id)
                self.repo.append_audit_log(
                    action="refresh_token",
                    actor=actor,
                    token_id=token_id,
                    result="ok",
                    detail=f"refresh merged and removed source token; target={int(existing_id)}",
                )
                return {"success": True, "token": self.repo.get_token(int(existing_id))}

            self.repo.update_token(
                token_id,
                refresh_token=new_refresh,
                status=status_by_quota,
                error_count=0,
                last_error_code="",
                last_error_message="",
                last_success_at=now,
                last_check_at=now,
                **quota_fields,
            )
            self.repo.upsert_health_snapshot(
                token_id=token_id,
                healthy=True,
                last_checked_at=now_ts,
                last_success_at=now_ts,
                last_error="",
                consecutive_failures=0,
                latency_ms=0,
            )
            self.repo.append_audit_log(
                action="refresh_token",
                actor=actor,
                token_id=token_id,
                result="ok",
                detail="refresh success",
            )
            return {"success": True, "token": self.repo.get_token(token_id)}

        err_msg = str(token_data.get("error")
                      or "refresh returned empty access token").strip()
        parsed_err = self.parse_refresh_error(err_msg)
        fail_status = "blocked" if self.is_hard_invalid_refresh_error(
            err_msg) else "cooldown"
        cooldown_until = "" if fail_status == "blocked" else _future_iso(
            _REFRESH_ERROR_COOLDOWN_SECONDS)
        self.repo.update_token(
            token_id,
            status=fail_status,
            error_count=int((self.repo.get_token(token_id)
                            or {}).get("error_count") or 0) + 1,
            last_check_at=now,
            last_error_code=parsed_err["code"],
            last_error_message=parsed_err["message"],
            cooldown_until=cooldown_until,
        )
        self.repo.upsert_health_snapshot(
            token_id=token_id,
            healthy=False,
            last_checked_at=now_ts,
            last_success_at=0.0,
            last_error=parsed_err["message"],
            consecutive_failures=1,
            latency_ms=0,
        )
        self.repo.append_audit_log(
            action="refresh_token",
            actor=actor,
            token_id=token_id,
            result="failed",
            detail=f"refresh failed after {_REFRESH_RETRY_COUNT} retries, status={fail_status}, err={err_msg[:180]}",
        )
        return {"success": False, "token": self.repo.get_token(token_id)}

    async def refresh_token_quota(self, token_id: int, actor: str) -> Dict[str, Any]:
        refresh_token = self.repo.get_refresh_token(token_id)
        if not refresh_token:
            raise ValueError("token not found")

        now = _utcnow_iso()
        token_data = await refresh_jwt_token(refresh_token_override=refresh_token)
        access = str(token_data.get("access_token")
                     or token_data.get("id_token") or "").strip()
        if not access:
            raise ValueError("refresh returned empty access token")

        quota = await get_request_limit(access)
        status_by_quota = self.status_by_quota(quota)
        quota_fields = self.quota_update_fields(quota, now)
        self.repo.update_token(
            token_id,
            status=status_by_quota,
            last_check_at=now,
            **quota_fields,
        )
        self.repo.append_audit_log(
            action="refresh_token_quota",
            actor=actor,
            token_id=token_id,
            result="ok",
            detail=(
                f"limit={int(quota.get('request_limit') or 0)} "
                f"used={int(quota.get('requests_used') or 0)}"
            ),
        )
        token = self.repo.get_token(token_id)
        return {"success": True, "quota": quota, "token": token}

    async def refresh_all(self, actor: str) -> Dict[str, Any]:
        items = self.repo.list_tokens()
        ok = 0
        failed = 0
        for item in items:
            token_id = int(item["id"])
            result = await self.refresh_token(token_id, actor=actor)
            if result.get("success"):
                ok += 1
            else:
                failed += 1
        return {"total": len(items), "success": ok, "failed": failed}
