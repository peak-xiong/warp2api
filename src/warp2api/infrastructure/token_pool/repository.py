from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Generator, Iterable, List, Optional

from warp2api.infrastructure.settings.settings import ROOT_DIR, get_token_db_path
from warp2api.infrastructure.utils.datetime import utcnow_iso
from warp2api.observability.logging import logger


_utcnow_iso = utcnow_iso


class TokenRepository:
    def __init__(self, db_path: Optional[str] = None) -> None:
        path = db_path or str(ROOT_DIR / "data" / "token_pool.db")
        self.db_path = Path(path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                timeout=30.0,
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("PRAGMA foreign_keys=ON;")
            conn.execute("PRAGMA busy_timeout=30000;")
            self._local.conn = conn
        return conn

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        conn = self._get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS token_accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    refresh_token TEXT UNIQUE,
                    email TEXT,
                    api_key TEXT,
                    id_token TEXT,
                    total_limit INTEGER,
                    used_limit INTEGER,
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
                    quota_remaining INTEGER,
                    quota_is_unlimited INTEGER,
                    quota_next_refresh_time TEXT,
                    quota_refresh_duration TEXT,
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
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_token_accounts_refresh_token
                ON token_accounts(refresh_token)
                WHERE refresh_token IS NOT NULL AND refresh_token <> ''
                """
            )
            self._assert_strict_schema(conn)

    def _table_columns(self, conn: sqlite3.Connection, table: str) -> set[str]:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return {str(r["name"]) for r in rows}

    def _assert_strict_schema(self, conn: sqlite3.Connection) -> None:
        account_cols = self._table_columns(conn, "token_accounts")
        health_cols = self._table_columns(conn, "token_health_snapshots")

        forbidden_account_cols = {
            "label", "token_hash", "refresh_token_encrypted"}
        forbidden_health_cols = {"token_preview"}
        bad_account = sorted(forbidden_account_cols.intersection(account_cols))
        bad_health = sorted(forbidden_health_cols.intersection(health_cols))
        if bad_account or bad_health:
            raise RuntimeError(
                "Unsupported legacy database schema detected. "
                f"forbidden token_accounts columns={bad_account}, "
                f"forbidden token_health_snapshots columns={bad_health}. "
                f"Please remove database and restart: {self.db_path}"
            )

    def _row_to_public(self, row: sqlite3.Row) -> Dict[str, Any]:
        token_plain = str(row["refresh_token"] or "")
        return {
            "id": row["id"],
            "warp_refresh_token": token_plain,
            "email": row["email"],
            "api_key": row["api_key"],
            "id_token": row["id_token"],
            "total_limit": row["total_limit"],
            "used_limit": row["used_limit"],
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
            "quota_remaining": row["quota_remaining"],
            "quota_is_unlimited": bool(int(row["quota_is_unlimited"])) if row["quota_is_unlimited"] is not None else None,
            "quota_next_refresh_time": row["quota_next_refresh_time"],
            "quota_refresh_duration": row["quota_refresh_duration"],
            "quota_updated_at": row["quota_updated_at"],
            "healthy": bool(int(row["healthy"])) if row["healthy"] is not None else None,
            "health_last_checked_at": row["health_last_checked_at"],
            "health_last_success_at": row["health_last_success_at"],
            "health_last_error": row["health_last_error"],
            "health_consecutive_failures": row["health_consecutive_failures"],
            "health_latency_ms": row["health_latency_ms"],
            "health_updated_at": row["health_updated_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def list_tokens(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    a.*,
                    h.healthy AS healthy,
                    h.last_checked_at AS health_last_checked_at,
                    h.last_success_at AS health_last_success_at,
                    h.last_error AS health_last_error,
                    h.consecutive_failures AS health_consecutive_failures,
                    h.latency_ms AS health_latency_ms,
                    h.updated_at AS health_updated_at
                FROM token_accounts a
                LEFT JOIN token_health_snapshots h ON h.token_id = a.id
                ORDER BY a.id DESC
                """
            ).fetchall()
        return [self._row_to_public(row) for row in rows]

    def get_token(self, token_id: int) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    a.*,
                    h.healthy AS healthy,
                    h.last_checked_at AS health_last_checked_at,
                    h.last_success_at AS health_last_success_at,
                    h.last_error AS health_last_error,
                    h.consecutive_failures AS health_consecutive_failures,
                    h.latency_ms AS health_latency_ms,
                    h.updated_at AS health_updated_at
                FROM token_accounts a
                LEFT JOIN token_health_snapshots h ON h.token_id = a.id
                WHERE a.id = ?
                """,
                (token_id,),
            ).fetchone()
        if not row:
            return None
        return self._row_to_public(row)

    def get_refresh_token(self, token_id: int) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT refresh_token FROM token_accounts WHERE id = ?",
                (token_id,),
            ).fetchone()
        if not row:
            return None
        token_plain = str(row["refresh_token"] or "").strip()
        return token_plain or None

    def find_token_id_by_refresh_token(self, refresh_token: str) -> Optional[int]:
        token = str(refresh_token or "").strip()
        if not token:
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM token_accounts WHERE refresh_token = ? LIMIT 1",
                (token,),
            ).fetchone()
        if not row:
            return None
        return int(row["id"])

    def delete_token(self, token_id: int) -> bool:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM token_health_snapshots WHERE token_id = ?",
                (token_id,),
            )
            cur = conn.execute(
                "DELETE FROM token_accounts WHERE id = ?",
                (token_id,),
            )
            return cur.rowcount == 1

    def delete_tokens(self, token_ids: Iterable[int]) -> Dict[str, int]:
        ids = sorted({int(i) for i in token_ids if int(i) > 0})
        if not ids:
            return {"requested": 0, "deleted": 0, "missing": 0}

        placeholders = ",".join(["?"] * len(ids))
        with self._connect() as conn:
            existing_rows = conn.execute(
                f"SELECT id FROM token_accounts WHERE id IN ({placeholders})",
                tuple(ids),
            ).fetchall()
            existing_ids = {int(r["id"]) for r in existing_rows}
            if existing_ids:
                ph_existing = ",".join(["?"] * len(existing_ids))
                conn.execute(
                    f"DELETE FROM token_health_snapshots WHERE token_id IN ({ph_existing})",
                    tuple(sorted(existing_ids)),
                )
                cur = conn.execute(
                    f"DELETE FROM token_accounts WHERE id IN ({ph_existing})",
                    tuple(sorted(existing_ids)),
                )
                deleted = int(cur.rowcount)
            else:
                deleted = 0

        requested = len(ids)
        missing = requested - deleted
        return {"requested": requested, "deleted": deleted, "missing": missing}

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
                existed = conn.execute(
                    "SELECT 1 FROM token_accounts WHERE refresh_token = ? LIMIT 1",
                    (token,),
                ).fetchone() is not None
                conn.execute(
                    """
                    INSERT INTO token_accounts (
                        refresh_token, status, created_at, updated_at
                    ) VALUES (?, 'active', ?, ?)
                    ON CONFLICT DO UPDATE SET
                        status='active',
                        updated_at=excluded.updated_at
                    """,
                    (token, now, now),
                )
                if existed:
                    duplicated += 1
                else:
                    inserted += 1
        return {"inserted": inserted, "duplicated": duplicated}

    def batch_import_accounts(self, accounts: Iterable[Dict[str, Any]]) -> Dict[str, int]:
        inserted = 0
        duplicated = 0
        updated = 0
        invalid = 0
        now = _utcnow_iso()
        seen = set()

        with self._connect() as conn:
            for raw in accounts:
                acc = raw or {}
                token = str(acc.get("refresh_token")
                            or "").strip().strip("'").strip('"')
                if not token:
                    invalid += 1
                    continue
                if token in seen:
                    continue
                seen.add(token)
                existed = conn.execute(
                    "SELECT 1 FROM token_accounts WHERE refresh_token = ? LIMIT 1",
                    (token,),
                ).fetchone() is not None

                email = str(acc.get("email") or "").strip() or None
                api_key = str(acc.get("api_key") or "").strip() or None
                id_token = str(acc.get("id_token") or "").strip() or None
                total_limit = acc.get("total_limit")
                used_limit = acc.get("used_limit")

                conn.execute(
                    """
                    INSERT INTO token_accounts (
                        refresh_token, email, api_key, id_token, total_limit, used_limit,
                        status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)
                    ON CONFLICT DO UPDATE SET
                        email = COALESCE(excluded.email, token_accounts.email),
                        api_key = COALESCE(excluded.api_key, token_accounts.api_key),
                        id_token = COALESCE(excluded.id_token, token_accounts.id_token),
                        total_limit = COALESCE(excluded.total_limit, token_accounts.total_limit),
                        used_limit = COALESCE(excluded.used_limit, token_accounts.used_limit),
                        status='active',
                        updated_at=excluded.updated_at
                    """,
                    (token, email, api_key, id_token,
                     total_limit, used_limit, now, now),
                )
                if existed:
                    duplicated += 1
                    updated += 1
                else:
                    inserted += 1

        return {"inserted": inserted, "duplicated": duplicated, "updated": updated, "invalid": invalid}

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
        fields: List[str] = []
        params: List[Any] = []

        if status is not None:
            fields.append("status = ?")
            params.append(status)
        if refresh_token is not None:
            fields.append("refresh_token = ?")
            params.append(refresh_token)
        if total_limit is not None:
            fields.append("total_limit = ?")
            params.append(int(total_limit))
        if used_limit is not None:
            fields.append("used_limit = ?")
            params.append(int(used_limit))
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
        if quota_limit is not None:
            fields.append("quota_limit = ?")
            params.append(int(quota_limit))
        if quota_used is not None:
            fields.append("quota_used = ?")
            params.append(int(quota_used))
        if quota_remaining is not None:
            fields.append("quota_remaining = ?")
            params.append(int(quota_remaining))
        if quota_is_unlimited is not None:
            fields.append("quota_is_unlimited = ?")
            params.append(1 if bool(quota_is_unlimited) else 0)
        if quota_next_refresh_time is not None:
            fields.append("quota_next_refresh_time = ?")
            params.append(quota_next_refresh_time)
        if quota_refresh_duration is not None:
            fields.append("quota_refresh_duration = ?")
            params.append(quota_refresh_duration)
        if quota_updated_at is not None:
            fields.append("quota_updated_at = ?")
            params.append(quota_updated_at)

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
            total = conn.execute(
                "SELECT COUNT(*) AS c FROM token_accounts").fetchone()["c"]
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
                (action, actor, token_id, result,
                 detail[:1000], _utcnow_iso()),
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
                    healthy,
                    last_checked_at,
                    last_success_at,
                    last_error,
                    consecutive_failures,
                    latency_ms,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(token_id) DO UPDATE SET
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
            row = conn.execute(
                "SELECT * FROM app_state WHERE key = ?", (key,)).fetchone()
        return dict(row) if row else None


_repo_singleton: Optional[TokenRepository] = None
_repo_db_path: Optional[str] = None


def get_token_repository() -> TokenRepository:
    global _repo_singleton, _repo_db_path
    db_path = get_token_db_path()
    if _repo_singleton is None or db_path != _repo_db_path:
        _repo_singleton = TokenRepository(db_path=db_path)
        _repo_db_path = db_path
        logger.info("Token repository initialized at %s",
                    _repo_singleton.db_path)
    return _repo_singleton
