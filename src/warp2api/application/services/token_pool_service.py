from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from warp2api.infrastructure.auth.jwt_auth import refresh_jwt_token
from warp2api.infrastructure.settings.settings import (
    get_token_db_path,
    WARP_TOKEN_COOLDOWN_SECONDS,
    WARP_TOKEN_ERROR_COOLDOWN_SECONDS,
    WARP_TOKEN_REFRESH_RETRY_BASE_DELAY_MS,
    WARP_TOKEN_REFRESH_RETRY_COUNT,
)
from warp2api.infrastructure.transport.warp_quota import get_request_limit
from warp2api.infrastructure.token_pool.repository import get_token_repository


ALLOWED_STATUSES = {"active", "cooldown", "blocked", "quota_exhausted", "disabled"}
_REFRESH_RETRY_COUNT = WARP_TOKEN_REFRESH_RETRY_COUNT
_REFRESH_RETRY_BASE_DELAY_MS = WARP_TOKEN_REFRESH_RETRY_BASE_DELAY_MS
_REFRESH_ERROR_COOLDOWN_SECONDS = WARP_TOKEN_ERROR_COOLDOWN_SECONDS


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(ts: Optional[str]) -> float:
    raw = (ts or "").strip()
    if not raw:
        return 0.0
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def _future_iso(seconds: int) -> str:
    return datetime.fromtimestamp(
        datetime.now(timezone.utc).timestamp() + float(seconds), tz=timezone.utc
    ).isoformat()


class TokenPoolService:
    def __init__(self) -> None:
        self.repo = get_token_repository()

    def list_tokens(self) -> List[Dict[str, Any]]:
        return self.repo.list_tokens()

    def get_token(self, token_id: int) -> Optional[Dict[str, Any]]:
        return self.repo.get_token(token_id)

    def batch_import(self, tokens: Iterable[str], actor: str = "admin") -> Dict[str, Any]:
        result = self.repo.batch_import(tokens=tokens)
        self.repo.append_audit_log(
            action="batch_import",
            actor=actor,
            token_id=None,
            result="ok",
            detail=f"inserted={result['inserted']} duplicated={result['duplicated']}",
        )
        return result

    @staticmethod
    def _normalize_tokens(tokens: Iterable[str]) -> List[str]:
        seen = set()
        out: List[str] = []
        for token in tokens:
            t = (token or "").strip().strip("'").strip('"')
            if not t or t in seen:
                continue
            seen.add(t)
            out.append(t)
        return out

    async def batch_import_and_hydrate(
        self,
        tokens: Iterable[str],
        actor: str = "admin",
        max_parallel: int = 3,
    ) -> Dict[str, Any]:
        cleaned = self._normalize_tokens(tokens)
        result = self.batch_import(cleaned, actor=actor)
        if not cleaned:
            result["hydrated"] = 0
            result["hydrate_failed"] = 0
            result["hydrated_token_ids"] = []
            return result

        sem = asyncio.Semaphore(max(1, int(max_parallel)))
        hydrated_ids: List[int] = []
        failed = 0

        async def _hydrate_one(refresh_token: str) -> None:
            nonlocal failed
            token_id = self.repo.find_token_id_by_refresh_token(refresh_token)
            if not token_id:
                failed += 1
                return
            async with sem:
                try:
                    data = await self.refresh_token(int(token_id), actor=f"{actor}:import")
                    if bool((data or {}).get("success")):
                        hydrated_ids.append(int(token_id))
                    else:
                        failed += 1
                except Exception:
                    failed += 1

        await asyncio.gather(*(_hydrate_one(t) for t in cleaned))
        result["hydrated"] = len(hydrated_ids)
        result["hydrate_failed"] = failed
        result["hydrated_token_ids"] = sorted(hydrated_ids)
        return result

    def batch_import_accounts(self, accounts: Iterable[Dict[str, Any]], actor: str = "admin") -> Dict[str, Any]:
        result = self.repo.batch_import_accounts(accounts=accounts)
        self.repo.append_audit_log(
            action="batch_import_accounts",
            actor=actor,
            token_id=None,
            result="ok",
            detail=(
                f"inserted={result['inserted']} duplicated={result['duplicated']} "
                f"updated={result['updated']} invalid={result['invalid']}"
            ),
        )
        return result

    def add_token(self, token: str, actor: str = "admin") -> Dict[str, Any]:
        return self.batch_import([token], actor=actor)

    def update_token(self, token_id: int, *, status: Optional[str], actor: str) -> Dict[str, Any]:
        if status is not None and status not in ALLOWED_STATUSES:
            raise ValueError(f"invalid status: {status}")
        ok = self.repo.update_token(token_id, status=status)
        if not ok:
            raise ValueError("token not found or unchanged")
        self.repo.append_audit_log(
            action="update_token",
            actor=actor,
            token_id=token_id,
            result="ok",
            detail=f"status={status!r}",
        )
        data = self.repo.get_token(token_id)
        return data or {}

    def delete_token(self, token_id: int, actor: str) -> Dict[str, Any]:
        token = self.repo.get_token(token_id)
        if not token:
            raise ValueError("token not found")
        ok = self.repo.delete_token(token_id)
        if not ok:
            raise ValueError("token not found")
        self.repo.append_audit_log(
            action="delete_token",
            actor=actor,
            token_id=token_id,
            result="ok",
            detail="deleted",
        )
        return {"deleted": True, "id": token_id}

    def batch_delete_tokens(self, token_ids: Iterable[int], actor: str) -> Dict[str, Any]:
        ids = [int(i) for i in token_ids]
        result = self.repo.delete_tokens(ids)
        self.repo.append_audit_log(
            action="batch_delete_tokens",
            actor=actor,
            token_id=None,
            result="ok",
            detail=(
                f"requested={result['requested']} deleted={result['deleted']} "
                f"missing={result['missing']}"
            ),
        )
        return result

    @staticmethod
    def _status_by_quota(quota_data: Dict[str, Any]) -> str:
        if not quota_data:
            return "active"
        q_limit = int(quota_data.get("request_limit") or 0)
        q_used = int(quota_data.get("requests_used") or 0)
        q_unlimited = bool(quota_data.get("is_unlimited") or False)
        if (not q_unlimited) and q_limit >= 0 and q_used >= q_limit:
            return "quota_exhausted"
        return "active"

    @staticmethod
    def _quota_update_fields(quota_data: Dict[str, Any], now_iso: str) -> Dict[str, Any]:
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

    @staticmethod
    def _is_quota_exhausted_error(status: int, err: str) -> bool:
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
        if TokenPoolService._is_quota_exhausted_error(status, low):
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

        msg_match = re.search(r'"message"\s*:\s*"([^"]+)"', raw, flags=re.IGNORECASE)
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
        is_quota = TokenPoolService._is_quota_exhausted_error(status, err)
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

    @staticmethod
    def _is_hard_invalid_refresh_error(error_message: str) -> bool:
        msg = (error_message or "").lower()
        return (
            "invalid_refresh_token" in msg
            or "invalid_grant" in msg
            or "refresh token is invalid" in msg
        )

    @staticmethod
    def _parse_refresh_error(raw_error: str) -> Dict[str, str]:
        raw = (raw_error or "").strip()
        if not raw:
            return {"code": "refresh_failed", "message": "refresh failed"}

        upper_raw = raw.upper()
        if "INVALID_REFRESH_TOKEN" in upper_raw:
            return {"code": "invalid_refresh_token", "message": "INVALID_REFRESH_TOKEN"}
        if "INVALID_GRANT" in upper_raw:
            return {"code": "invalid_grant", "message": "INVALID_GRANT"}

        # securetoken JSON body usually contains:
        # "message": "INVALID_REFRESH_TOKEN", "status": "INVALID_ARGUMENT"
        message_match = re.search(r'"message"\s*:\s*"([^"]+)"', raw, flags=re.IGNORECASE)
        status_match = re.search(r'"status"\s*:\s*"([^"]+)"', raw, flags=re.IGNORECASE)
        code_match = re.search(r'"code"\s*:\s*(\d+)', raw, flags=re.IGNORECASE)

        parsed_message = (message_match.group(1).strip() if message_match else "").strip()
        parsed_status = (status_match.group(1).strip() if status_match else "").strip()
        parsed_http_code = (code_match.group(1).strip() if code_match else "").strip()

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

    async def _refresh_with_retry(self, refresh_token: str) -> Dict[str, Any]:
        last_error = ""
        for i in range(_REFRESH_RETRY_COUNT):
            try:
                token_data = await refresh_jwt_token(refresh_token_override=refresh_token)
            except Exception as exc:
                token_data = {}
                last_error = str(exc)

            access = str(token_data.get("access_token") or token_data.get("id_token") or "").strip()
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
        now_ts = datetime.now(timezone.utc).timestamp()
        token_data = await self._refresh_with_retry(refresh_token)
        new_refresh = str(token_data.get("refresh_token") or refresh_token).strip()
        access = str(token_data.get("access_token") or token_data.get("id_token") or "").strip()

        if access:
            quota_data: Dict[str, Any] = {}
            try:
                quota_data = get_request_limit(access)
            except Exception:
                quota_data = {}
            status_by_quota = self._status_by_quota(quota_data)
            quota_fields = self._quota_update_fields(quota_data, now)

            # Upsert-by-refresh-token semantics: if refreshed token already belongs to
            # another row, merge into that canonical row instead of raising UNIQUE errors.
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

                # Keep token_accounts as a current-state snapshot.
                # When a token refresh resolves to another existing token, remove
                # the merged source row instead of persisting historical placeholders.
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

        err_msg = str(token_data.get("error") or "refresh returned empty access token").strip()
        parsed_err = self._parse_refresh_error(err_msg)
        fail_status = "blocked" if self._is_hard_invalid_refresh_error(err_msg) else "cooldown"
        cooldown_until = "" if fail_status == "blocked" else _future_iso(_REFRESH_ERROR_COOLDOWN_SECONDS)
        self.repo.update_token(
            token_id,
            status=fail_status,
            error_count=int((self.repo.get_token(token_id) or {}).get("error_count") or 0) + 1,
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
        access = str(token_data.get("access_token") or token_data.get("id_token") or "").strip()
        if not access:
            raise ValueError("refresh returned empty access token")

        quota = get_request_limit(access)
        status_by_quota = self._status_by_quota(quota)
        quota_fields = self._quota_update_fields(quota, now)
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

        update_fields = {
            "status": status,
            "error_count": next_err,
            "last_error_code": err_code,
            "last_error_message": err_msg,
            "last_check_at": now,
            "cooldown_until": cooldown_until,
        }
        # Keep quota state explicit for UI/scheduler if upstream says token quota is exhausted.
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
        cooldown_until = "" if status == "blocked" else _future_iso(WARP_TOKEN_ERROR_COOLDOWN_SECONDS)
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

    async def health_check_token(self, token_id: int, actor: str) -> Dict[str, Any]:
        return await self.refresh_token(token_id, actor=actor)

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

    def statistics(self) -> Dict[str, Any]:
        return self.repo.statistics()

    def events(self, limit: int = 100) -> List[Dict[str, Any]]:
        return self.repo.list_audit_logs(limit=limit)

    def health(self) -> Dict[str, Any]:
        from warp2api.infrastructure.monitoring.account_pool_monitor import get_monitor_status
        return get_monitor_status()

    def readiness(self) -> Dict[str, Any]:
        items = self.repo.list_tokens()
        now_ts = datetime.now(timezone.utc).timestamp()

        total = len(items)
        available = 0
        blocked = 0
        disabled = 0
        quota = 0
        cooldown = 0
        soonest_recovery_seconds: Optional[int] = None

        for item in items:
            status = str(item.get("status") or "")
            cooldown_until = str(item.get("cooldown_until") or "")
            cooldown_remaining = max(0, int(_parse_iso(cooldown_until) - now_ts)) if cooldown_until else 0

            if status == "active":
                if cooldown_remaining == 0:
                    available += 1
                else:
                    cooldown += 1
            elif status == "cooldown":
                cooldown += 1
            elif status == "blocked":
                blocked += 1
            elif status == "disabled":
                disabled += 1
            elif status == "quota_exhausted":
                quota += 1
                quota_next = str(item.get("quota_next_refresh_time") or "")
                quota_recover = max(0, int(_parse_iso(quota_next) - now_ts)) if quota_next else 0
                if quota_recover > 0:
                    if soonest_recovery_seconds is None or quota_recover < soonest_recovery_seconds:
                        soonest_recovery_seconds = quota_recover

            if cooldown_remaining > 0:
                if soonest_recovery_seconds is None or cooldown_remaining < soonest_recovery_seconds:
                    soonest_recovery_seconds = cooldown_remaining

        ready = available > 0
        return {
            "ready": ready,
            "reason": "ok" if ready else "no_available_token",
            "total_tokens": total,
            "available_tokens": available,
            "blocked_tokens": blocked,
            "disabled_tokens": disabled,
            "quota_exhausted_tokens": quota,
            "cooldown_tokens": cooldown,
            "soonest_recovery_seconds": soonest_recovery_seconds,
        }


_service_singleton: Optional[TokenPoolService] = None
_service_db_path: Optional[str] = None


def get_token_pool_service() -> TokenPoolService:
    global _service_singleton, _service_db_path
    db_path = get_token_db_path()
    if _service_singleton is None or _service_db_path != db_path:
        _service_singleton = TokenPoolService()
        _service_db_path = db_path
    return _service_singleton
