from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TokenAccount:
    """Domain entity representing a token pool account."""

    id: int
    warp_refresh_token: str = ""
    email: Optional[str] = None
    api_key: Optional[str] = None
    id_token: Optional[str] = None

    # Quota
    total_limit: Optional[int] = None
    used_limit: Optional[int] = None
    quota_limit: Optional[int] = None
    quota_used: Optional[int] = None
    quota_remaining: Optional[int] = None
    quota_is_unlimited: Optional[bool] = None
    quota_next_refresh_time: Optional[str] = None
    quota_refresh_duration: Optional[str] = None
    quota_updated_at: Optional[str] = None

    # Status & errors
    status: str = "active"
    error_count: int = 0
    last_error_code: Optional[str] = None
    last_error_message: Optional[str] = None
    last_success_at: Optional[str] = None
    last_check_at: Optional[str] = None
    cooldown_until: Optional[str] = None
    use_count: int = 0

    # Health snapshot (joined from token_health_snapshots)
    healthy: Optional[bool] = None
    health_last_checked_at: Optional[float] = None
    health_last_success_at: Optional[float] = None
    health_last_error: Optional[str] = None
    health_consecutive_failures: Optional[int] = None
    health_latency_ms: Optional[int] = None
    health_updated_at: Optional[str] = None

    # Timestamps
    created_at: str = ""
    updated_at: str = ""

    @property
    def is_available(self) -> bool:
        """True when the account is active and not in cooldown."""
        return self.status == "active"

    @property
    def is_quota_exhausted(self) -> bool:
        if self.quota_is_unlimited:
            return False
        if self.quota_limit is not None and self.quota_used is not None:
            return self.quota_used >= self.quota_limit
        return self.status == "quota_exhausted"

    def to_dict(self) -> dict:
        """Convert to the same dict format used by repository._row_to_public."""
        from dataclasses import asdict
        return asdict(self)
