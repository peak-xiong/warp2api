from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from warp2api.infrastructure.auth.jwt_auth import refresh_jwt_token
from warp2api.infrastructure.token_pool.repository import get_token_repository


ALLOWED_STATUSES = {"active", "cooldown", "blocked", "quota_exhausted", "disabled"}


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

    async def refresh_token(self, token_id: int, actor: str) -> Dict[str, Any]:
        refresh_token = self.repo.get_refresh_token(token_id)
        if not refresh_token:
            raise ValueError("token not found")

        now = _utcnow_iso()
        token_data = await refresh_jwt_token(refresh_token_override=refresh_token)
        new_refresh = str(token_data.get("refresh_token") or refresh_token).strip()
        access = str(token_data.get("access_token") or token_data.get("id_token") or "").strip()

        if access:
            self.repo.update_token(
                token_id,
                refresh_token=new_refresh,
                status="active",
                error_count=0,
                last_error_code="",
                last_error_message="",
                last_success_at=now,
                last_check_at=now,
            )
            self.repo.append_audit_log(
                action="refresh_token",
                actor=actor,
                token_id=token_id,
                result="ok",
                detail="refresh success",
            )
            return {"success": True, "token": self.repo.get_token(token_id)}

        self.repo.update_token(
            token_id,
            status="blocked",
            last_check_at=now,
            last_error_code="refresh_failed",
            last_error_message="refresh returned empty access token",
        )
        self.repo.append_audit_log(
            action="refresh_token",
            actor=actor,
            token_id=token_id,
            result="failed",
            detail="empty access token",
        )
        return {"success": False, "token": self.repo.get_token(token_id)}

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
    db_path = (os.getenv("WARP_TOKEN_DB_PATH") or "").strip() or None
    if _service_singleton is None or _service_db_path != db_path:
        _service_singleton = TokenPoolService()
        _service_db_path = db_path
    return _service_singleton
