from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict


_LOCKS: Dict[int, asyncio.Lock] = {}
_LOCKS_GUARD = asyncio.Lock()


async def _get_lock(token_id: int) -> asyncio.Lock:
    async with _LOCKS_GUARD:
        lock = _LOCKS.get(token_id)
        if lock is None:
            lock = asyncio.Lock()
            _LOCKS[token_id] = lock
        return lock


@asynccontextmanager
async def token_lock(token_id: int) -> AsyncIterator[None]:
    lock = await _get_lock(token_id)
    await lock.acquire()
    try:
        yield
    finally:
        lock.release()

