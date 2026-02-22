from __future__ import annotations

import re
from typing import Any, Dict

from warp2api.domain.protocols.token_repository import TokenRepositoryProtocol
from warp2api.infrastructure.settings.settings import (
    WARP_TOKEN_COOLDOWN_SECONDS,
    WARP_TOKEN_ERROR_COOLDOWN_SECONDS,
)
from warp2api.infrastructure.utils.datetime import future_iso, utcnow_iso

_utcnow_iso = utcnow_iso
_future_iso = future_iso


class TokenRuntimeService:
    """Handles runtime request result tracking and error classification."""

    def __init__(self, repo: TokenRepositoryProtocol) -> None:
        self.repo = repo

    # ------------------------------------------------------------------
    # Error classification (static)
    # ------------------------------------------------------------------

    @staticmethod
    def is_quota_exhausted_error(status: int, err: str) -> bool:
        low = (err or "").lower()
        if "no remaining quota" in low or "no ai requests remaining" in low:
            return True
        return status == 429 and ("quota" in low and ("exhaust" in low or "remain" in low))

    @staticmethod
    def parse_runtime_request_error(result: Dict[str, Any]) -> Dict[str, str]:
        status = int(result.get("status_code") or 0)
        raw = str(result.get("error") or "").strip()
        low = raw.lower()

        if "invalid_refresh_token" in low:
            return {"code": "invalid_refresh_token", "message": "INVALID_REFRESH_TOKEN"}
        if "invalid_grant" in low:
            return {"code": "invalid_grant", "message": "INVALID_GRANT"}
        if TokenRuntimeService.is_quota_exhausted_error(status, low):
            return {"code": "quota_exhausted", "message": "NO_REMAINING_QUOTA"}
        if "failed to fetch" in low:
            return {"code": "failed_to_fetch", "message": "Failed to fetch"}
        if "timed out" in low or "timeout" in low:
            return {"code": "timeout", "message": "Request timeout"}
        if "connection refused" in low:
            return {"code": "connection_refused", "message": "Connection refused"}
        if "connection reset" in low:
            return {"code": "connection_reset", "message": "Connection reset"}
        if "something went wrong with this conversation" in low:
            return {"code": "conversation_error", "message": "Something went wrong with this conversation"}

        msg_match = re.search(
            r'"message"\s*:\s*"([^"]+)"', raw, flags=re.IGNORECASE)
        if msg_match:
            msg = msg_match.group(1).strip()
            return {"code": msg.lower()[:64], "message": msg[:240]}

        if status:
            return {"code": f"http_{status}", "message": (raw or f"HTTP {status}")[:240]}
        return {"code": "request_failed", "message": (raw or "request failed")[:240]}

    @staticmethod
    def status_from_runtime_result(result: Dict[str, Any]) -> str:
        status = int(result.get("status_code") or 0)
        err = str(result.get("error") or "").lower()
        is_quota = TokenRuntimeService.is_quota_exhausted_error(status, err)
        if is_quota:
            return "quota_exhausted"
        if status == 0:
            return "cooldown"
        if status == 403:
            return "blocked"
        if status in (401, 429):
            return "cooldown"
        if status >= 500:
            return "cooldown"
        if "invalid_grant" in err:
            return "blocked"
        return "active"

    # ------------------------------------------------------------------
    # Runtime result marking
    # ------------------------------------------------------------------

    def mark_runtime_request_result(self, token_id: int, result: Dict[str, Any], actor: str = "runtime") -> None:
        now = _utcnow_iso()
        token = self.repo.get_token(token_id)
        if not token:
            return

        curr_err = int(token.get("error_count") or 0)
        err_info = self.parse_runtime_request_error(result)
        err_msg = err_info["message"][:240]
        err_code = err_info["code"][:64]
        status = self.status_from_runtime_result(result)

        if result.get("ok"):
            self.repo.increment_use_count(token_id)
            self.repo.update_token(
                token_id,
                status="active",
                error_count=0,
                last_error_code="",
                last_error_message="",
                last_success_at=now,
                last_check_at=now,
                cooldown_until="",
            )
            self.repo.append_audit_log(
                action="runtime_send",
                actor=actor,
                token_id=token_id,
                result="ok",
                detail=f"status={result.get('status_code')}",
            )
            return

        next_err = curr_err + 1
        cooldown_until = ""
        if status == "cooldown":
            cooldown_until = _future_iso(WARP_TOKEN_ERROR_COOLDOWN_SECONDS)
        if status == "quota_exhausted":
            cooldown_until = _future_iso(WARP_TOKEN_COOLDOWN_SECONDS)

        update_fields: Dict[str, Any] = {
            "status": status,
            "error_count": next_err,
            "last_error_code": err_code,
            "last_error_message": err_msg,
            "last_check_at": now,
            "cooldown_until": cooldown_until,
        }
        if status == "quota_exhausted":
            q_limit = token.get("quota_limit")
            t_limit = token.get("total_limit")
            limit = q_limit if q_limit is not None else t_limit
            update_fields["quota_remaining"] = 0
            update_fields["quota_updated_at"] = now
            if isinstance(limit, int) and limit >= 0:
                update_fields["quota_used"] = limit
                update_fields["used_limit"] = limit

        self.repo.update_token(
            token_id,
            **update_fields,
        )
        self.repo.append_audit_log(
            action="runtime_send",
            actor=actor,
            token_id=token_id,
            result="failed",
            detail=f"status={result.get('status_code')} mapped_status={status} err={err_msg}",
        )

    def mark_runtime_refresh_error(self, token_id: int, error: Exception, actor: str = "runtime") -> None:
        now = _utcnow_iso()
        token = self.repo.get_token(token_id)
        if not token:
            return
        curr_err = int(token.get("error_count") or 0)
        msg = str(error)[:240]
        status = "blocked" if "invalid_grant" in msg.lower() else "cooldown"
        cooldown_until = "" if status == "blocked" else _future_iso(
            WARP_TOKEN_ERROR_COOLDOWN_SECONDS)
        self.repo.update_token(
            token_id,
            status=status,
            error_count=curr_err + 1,
            last_error_code="refresh_error",
            last_error_message=msg,
            last_check_at=now,
            cooldown_until=cooldown_until,
        )
        self.repo.append_audit_log(
            action="runtime_refresh",
            actor=actor,
            token_id=token_id,
            result="failed",
            detail=f"mapped_status={status} err={msg}",
        )
