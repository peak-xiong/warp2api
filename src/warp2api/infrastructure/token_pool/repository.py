from __future__ import annotations

import os
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from warp2api.infrastructure.settings.settings import ROOT_DIR
from warp2api.observability.logging import logger

from .crypto import decrypt_refresh_token, encrypt_refresh_token, token_hash, token_preview


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TokenRepository:
    def __init__(self, db_path: Optional[str] = None) -> None:
        path = db_path or str(ROOT_DIR / "data" / "token_pool.db")
        self.db_path = Path(path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS token_accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    label TEXT,
                    token_hash TEXT NOT NULL UNIQUE,
                    refresh_token_encrypted TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    error_count INTEGER NOT NULL DEFAULT 0,
                    last_error_code TEXT,
                    last_error_message TEXT,
                    last_success_at TEXT,
                    last_check_at TEXT,
                    cooldown_until TEXT,
                    use_count INTEGER NOT NULL DEFAULT 0,
                    quota_limit INTEGER,
                    quota_used INTEGER,
                    quota_updated_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS token_audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    token_id INTEGER,
                    result TEXT NOT NULL,
                    detail TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS token_health_snapshots (
                    token_id INTEGER PRIMARY KEY,
                    token_preview TEXT NOT NULL,
                    healthy INTEGER NOT NULL DEFAULT 0,
                    last_checked_at REAL NOT NULL DEFAULT 0,
                    last_success_at REAL NOT NULL DEFAULT 0,
                    last_error TEXT,
                    consecutive_failures INTEGER NOT NULL DEFAULT 0,
                    latency_ms INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS app_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

    def _row_to_public(self, row: sqlite3.Row) -> Dict[str, Any]:
        try:
            token_plain = decrypt_refresh_token(row["refresh_token_encrypted"])
        except Exception:
            token_plain = ""
        return {
            "id": row["id"],
            "label": row["label"],
            "token_preview": token_preview(token_plain),
            "status": row["status"],
            "error_count": row["error_count"],
            "last_error_code": row["last_error_code"],
            "last_error_message": row["last_error_message"],
            "last_success_at": row["last_success_at"],
            "last_check_at": row["last_check_at"],
            "cooldown_until": row["cooldown_until"],
            "use_count": row["use_count"],
            "quota_limit": row["quota_limit"],
            "quota_used": row["quota_used"],
            "quota_updated_at": row["quota_updated_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def list_tokens(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM token_accounts ORDER BY id DESC").fetchall()
        return [self._row_to_public(row) for row in rows]

    def get_token(self, token_id: int) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM token_accounts WHERE id = ?", (token_id,)).fetchone()
        if not row:
            return None
        return self._row_to_public(row)

    def get_refresh_token(self, token_id: int) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT refresh_token_encrypted FROM token_accounts WHERE id = ?",
                (token_id,),
            ).fetchone()
        if not row:
            return None
        return decrypt_refresh_token(row["refresh_token_encrypted"])

    def increment_use_count(self, token_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE token_accounts SET use_count = use_count + 1, updated_at = ? WHERE id = ?",
                (_utcnow_iso(), token_id),
            )
            return cur.rowcount == 1

    def batch_import(self, tokens: Iterable[str]) -> Dict[str, int]:
        inserted = 0
        duplicated = 0
        now = _utcnow_iso()
        cleaned = []
        seen = set()
        for token in tokens:
            t = (token or "").strip().strip("'").strip('"')
            if not t:
                continue
            if t in seen:
                continue
            seen.add(t)
            cleaned.append(t)

        with self._connect() as conn:
            for token in cleaned:
                th = token_hash(token)
                encrypted = encrypt_refresh_token(token)
                label = self._generate_unique_label(conn)
                cur = conn.execute(
                    """
                    INSERT OR IGNORE INTO token_accounts (
                        label, token_hash, refresh_token_encrypted, status, created_at, updated_at
                    ) VALUES (?, ?, ?, 'active', ?, ?)
                    """,
                    (label, th, encrypted, now, now),
                )
                if cur.rowcount == 1:
                    inserted += 1
                else:
                    duplicated += 1
        return {"inserted": inserted, "duplicated": duplicated}

    def _generate_unique_label(self, conn: sqlite3.Connection) -> str:
        # Unified random label format for all imported tokens.
        for _ in range(8):
            candidate = f"tk-{secrets.token_hex(4)}"
            row = conn.execute(
                "SELECT 1 FROM token_accounts WHERE label = ? LIMIT 1",
                (candidate,),
            ).fetchone()
            if not row:
                return candidate
        return f"tk-{secrets.token_hex(8)}"

    def update_token(
        self,
        token_id: int,
        *,
        label: Optional[str] = None,
        status: Optional[str] = None,
        refresh_token: Optional[str] = None,
        error_count: Optional[int] = None,
        last_error_code: Optional[str] = None,
        last_error_message: Optional[str] = None,
        last_success_at: Optional[str] = None,
        last_check_at: Optional[str] = None,
        cooldown_until: Optional[str] = None,
        use_count: Optional[int] = None,
    ) -> bool:
        fields: List[str] = []
        params: List[Any] = []

        if label is not None:
            fields.append("label = ?")
            params.append(label)
        if status is not None:
            fields.append("status = ?")
            params.append(status)
        if refresh_token is not None:
            fields.append("token_hash = ?")
            params.append(token_hash(refresh_token))
            fields.append("refresh_token_encrypted = ?")
            params.append(encrypt_refresh_token(refresh_token))
        if error_count is not None:
            fields.append("error_count = ?")
            params.append(error_count)
        if last_error_code is not None:
            fields.append("last_error_code = ?")
            params.append(last_error_code)
        if last_error_message is not None:
            fields.append("last_error_message = ?")
            params.append(last_error_message)
        if last_success_at is not None:
            fields.append("last_success_at = ?")
            params.append(last_success_at)
        if last_check_at is not None:
            fields.append("last_check_at = ?")
            params.append(last_check_at)
        if cooldown_until is not None:
            fields.append("cooldown_until = ?")
            params.append(cooldown_until)
        if use_count is not None:
            fields.append("use_count = ?")
            params.append(use_count)

        if not fields:
            return False

        fields.append("updated_at = ?")
        params.append(_utcnow_iso())
        params.append(token_id)

        query = f"UPDATE token_accounts SET {', '.join(fields)} WHERE id = ?"
        with self._connect() as conn:
            cur = conn.execute(query, tuple(params))
            return cur.rowcount == 1

    def statistics(self) -> Dict[str, Any]:
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) AS c FROM token_accounts").fetchone()["c"]
            by_status_rows = conn.execute(
                "SELECT status, COUNT(*) AS c FROM token_accounts GROUP BY status"
            ).fetchall()
        by_status = {row["status"]: row["c"] for row in by_status_rows}
        return {"total": total, "by_status": by_status}

    def append_audit_log(
        self,
        *,
        action: str,
        actor: str,
        token_id: Optional[int],
        result: str,
        detail: str = "",
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO token_audit_logs (action, actor, token_id, result, detail, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (action, actor, token_id, result, detail[:1000], _utcnow_iso()),
            )

    def list_audit_logs(self, limit: int = 100) -> List[Dict[str, Any]]:
        safe_limit = max(1, min(500, int(limit)))
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM token_audit_logs ORDER BY id DESC LIMIT ?",
                (safe_limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_health_snapshot(self, token_id: int) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM token_health_snapshots WHERE token_id = ?",
                (token_id,),
            ).fetchone()
        return dict(row) if row else None

    def upsert_health_snapshot(
        self,
        *,
        token_id: int,
        token_preview: str,
        healthy: bool,
        last_checked_at: float,
        last_success_at: float,
        last_error: str,
        consecutive_failures: int,
        latency_ms: int,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO token_health_snapshots (
                    token_id,
                    token_preview,
                    healthy,
                    last_checked_at,
                    last_success_at,
                    last_error,
                    consecutive_failures,
                    latency_ms,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(token_id) DO UPDATE SET
                    token_preview=excluded.token_preview,
                    healthy=excluded.healthy,
                    last_checked_at=excluded.last_checked_at,
                    last_success_at=excluded.last_success_at,
                    last_error=excluded.last_error,
                    consecutive_failures=excluded.consecutive_failures,
                    latency_ms=excluded.latency_ms,
                    updated_at=excluded.updated_at
                """,
                (
                    token_id,
                    token_preview,
                    1 if healthy else 0,
                    float(last_checked_at),
                    float(last_success_at),
                    str(last_error or "")[:240],
                    int(consecutive_failures),
                    int(latency_ms),
                    _utcnow_iso(),
                ),
            )

    def list_health_snapshots(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM token_health_snapshots ORDER BY token_id ASC"
            ).fetchall()
        out: List[Dict[str, Any]] = []
        for row in rows:
            d = dict(row)
            d["healthy"] = bool(int(d.get("healthy") or 0))
            out.append(d)
        return out

    def set_app_state(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO app_state (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value=excluded.value,
                    updated_at=excluded.updated_at
                """,
                (key, value, _utcnow_iso()),
            )

    def get_app_state(self, key: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM app_state WHERE key = ?", (key,)).fetchone()
        return dict(row) if row else None


_repo_singleton: Optional[TokenRepository] = None
_repo_db_path: Optional[str] = None


def get_token_repository() -> TokenRepository:
    global _repo_singleton, _repo_db_path
    db_path = (os.getenv("WARP_TOKEN_DB_PATH") or "").strip() or None
    if _repo_singleton is None or db_path != _repo_db_path:
        _repo_singleton = TokenRepository(db_path=db_path)
        _repo_db_path = db_path
        logger.info("Token repository initialized at %s", _repo_singleton.db_path)
    return _repo_singleton
