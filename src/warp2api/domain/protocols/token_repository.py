from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Protocol


class TokenRepositoryProtocol(Protocol):

    def list_tokens(self) -> List[Dict[str, Any]]:
        ...

    def get_token(self, token_id: int) -> Optional[Dict[str, Any]]:
        ...

    def get_refresh_token(self, token_id: int) -> Optional[str]:
        ...

    def find_token_id_by_refresh_token(self, refresh_token: str) -> Optional[int]:
        ...

    def delete_token(self, token_id: int) -> bool:
        ...

    def delete_tokens(self, token_ids: Iterable[int]) -> Dict[str, int]:
        ...

    def increment_use_count(self, token_id: int) -> bool:
        ...

    def batch_import(self, tokens: Iterable[str]) -> Dict[str, int]:
        ...

    def batch_import_accounts(self, accounts: Iterable[Dict[str, Any]]) -> Dict[str, int]:
        ...

    def update_token(
        self,
        token_id: int,
        *,
        status: Optional[str] = None,
        refresh_token: Optional[str] = None,
        total_limit: Optional[int] = None,
        used_limit: Optional[int] = None,
        error_count: Optional[int] = None,
        last_error_code: Optional[str] = None,
        last_error_message: Optional[str] = None,
        last_success_at: Optional[str] = None,
        last_check_at: Optional[str] = None,
        cooldown_until: Optional[str] = None,
        use_count: Optional[int] = None,
        quota_limit: Optional[int] = None,
        quota_used: Optional[int] = None,
        quota_remaining: Optional[int] = None,
        quota_is_unlimited: Optional[bool] = None,
        quota_next_refresh_time: Optional[str] = None,
        quota_refresh_duration: Optional[str] = None,
        quota_updated_at: Optional[str] = None,
    ) -> bool:
        ...

    def statistics(self) -> Dict[str, Any]:
        ...

    def append_audit_log(
        self,
        *,
        action: str,
        actor: str,
        token_id: Optional[int],
        result: str,
        detail: str = "",
    ) -> None:
        ...

    def list_audit_logs(self, limit: int = 100) -> List[Dict[str, Any]]:
        ...

    def get_health_snapshot(self, token_id: int) -> Optional[Dict[str, Any]]:
        ...

    def upsert_health_snapshot(
        self,
        *,
        token_id: int,
        healthy: bool,
        last_checked_at: float,
        last_success_at: float,
        last_error: str,
        consecutive_failures: int,
        latency_ms: int,
    ) -> None:
        ...

    def list_health_snapshots(self) -> List[Dict[str, Any]]:
        ...

    def set_app_state(self, key: str, value: str) -> None:
        ...

    def get_app_state(self, key: str) -> Optional[Dict[str, Any]]:
        ...
