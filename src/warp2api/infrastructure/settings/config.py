from __future__ import annotations

from dataclasses import dataclass

from warp2api.infrastructure.settings.settings import (
    CLIENT_VERSION,
    HOST,
    OS_CATEGORY,
    OS_NAME,
    OS_VERSION,
    PORT,
    STRICT_ENV,
    WARP_URL,
)


@dataclass(frozen=True)
class Settings:
    host: str = HOST
    port: int = PORT
    warp_url: str = WARP_URL
    strict_env: bool = STRICT_ENV
    client_version: str = CLIENT_VERSION
    os_category: str = OS_CATEGORY
    os_name: str = OS_NAME
    os_version: str = OS_VERSION
