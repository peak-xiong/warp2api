from __future__ import annotations

import asyncio
from typing import Any, Dict, Iterable, List, Optional

from warp2api.infrastructure.utils.datetime import utcnow_iso, parse_iso, utcnow_timestamp
from warp2api.infrastructure.settings.settings import get_token_db_path
from warp2api.infrastructure.token_pool.repository import get_token_repository
from warp2api.domain.protocols.token_repository import TokenRepositoryProtocol

from warp2api.application.services.token_refresh_service import TokenRefreshService
from warp2api.application.services.token_runtime_service import TokenRuntimeService


ALLOWED_STATUSES = {"active", "cooldown",
                    "blocked", "quota_exhausted", "disabled"}

_parse_iso = parse_iso


class TokenPoolService:
    """Facade for token pool operations.

    Delegates refresh logic to :class:`TokenRefreshService` and runtime
    result tracking to :class:`TokenRuntimeService`.
    """

    def __init__(self) -> None:
        self.repo: TokenRepositoryProtocol = get_token_repository()
        self._refresh = TokenRefreshService(self.repo)
        self._runtime = TokenRuntimeService(self.repo)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Refresh (delegated)
    # ------------------------------------------------------------------

    async def refresh_token(self, token_id: int, actor: str) -> Dict[str, Any]:
        return await self._refresh.refresh_token(token_id, actor=actor)

    async def refresh_token_quota(self, token_id: int, actor: str) -> Dict[str, Any]:
        return await self._refresh.refresh_token_quota(token_id, actor=actor)

    async def health_check_token(self, token_id: int, actor: str) -> Dict[str, Any]:
        return await self._refresh.refresh_token(token_id, actor=actor)

    async def refresh_all(self, actor: str) -> Dict[str, Any]:
        return await self._refresh.refresh_all(actor=actor)

    # ------------------------------------------------------------------
    # Runtime result tracking (delegated)
    # ------------------------------------------------------------------

    @staticmethod
    def parse_runtime_request_error(result: Dict[str, Any]) -> Dict[str, str]:
        return TokenRuntimeService.parse_runtime_request_error(result)

    @staticmethod
    def status_from_runtime_result(result: Dict[str, Any]) -> str:
        return TokenRuntimeService.status_from_runtime_result(result)

    def mark_runtime_request_result(self, token_id: int, result: Dict[str, Any], actor: str = "runtime") -> None:
        self._runtime.mark_runtime_request_result(token_id, result, actor=actor)

    def mark_runtime_refresh_error(self, token_id: int, error: Exception, actor: str = "runtime") -> None:
        self._runtime.mark_runtime_refresh_error(token_id, error, actor=actor)

    # ------------------------------------------------------------------
    # Statistics & readiness
    # ------------------------------------------------------------------

    def statistics(self) -> Dict[str, Any]:
        return self.repo.statistics()

    def events(self, limit: int = 100) -> List[Dict[str, Any]]:
        return self.repo.list_audit_logs(limit=limit)

    def health(self) -> Dict[str, Any]:
        from warp2api.infrastructure.monitoring.account_pool_monitor import get_monitor_status
        return get_monitor_status()

    def readiness(self) -> Dict[str, Any]:
        items = self.repo.list_tokens()
        now_ts = utcnow_timestamp()

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
            cooldown_remaining = max(
                0, int(_parse_iso(cooldown_until) - now_ts)) if cooldown_until else 0

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
                quota_recover = max(
                    0, int(_parse_iso(quota_next) - now_ts)) if quota_next else 0
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
