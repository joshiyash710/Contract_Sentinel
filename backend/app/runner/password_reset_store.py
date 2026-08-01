"""
Thread-safe SQLite store for password-reset tokens (feature 034).

Mirrors UserStore's lock/connection discipline (feature 014/012): one shared sqlite3 connection with
check_same_thread=False, guarded by a threading.Lock. Schema is owned by Alembic migration 0008 — this
class assumes upgrade_to_head has already run.

Stores only the HMAC of a token (never the raw token); hashing is done by the caller
(security.hash_reset_token). Tokens are single-use (used_at) and time-limited (expires_at).
"""

import sqlite3
import threading
from dataclasses import dataclass
from typing import Optional


@dataclass
class ResetTokenRow:
    id: str
    user_id: str
    token_hash: str
    created_at: str
    expires_at: str
    used_at: Optional[str] = None


class PasswordResetStore:
    def __init__(self, db_path: str) -> None:
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def create(
        self, token_id: str, user_id: str, token_hash: str, created_at: str, expires_at: str
    ) -> str:
        """Insert a new reset-token row (already hashed by the caller). Returns its id."""
        with self._lock:
            self._conn.execute(
                "INSERT INTO password_reset_tokens "
                "(id, user_id, token_hash, created_at, expires_at, used_at) "
                "VALUES (?, ?, ?, ?, ?, NULL)",
                (token_id, user_id, token_hash, created_at, expires_at),
            )
            self._conn.commit()
        return token_id

    def get_by_hash(self, token_hash: str) -> Optional[ResetTokenRow]:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, user_id, token_hash, created_at, expires_at, used_at "
                "FROM password_reset_tokens WHERE token_hash = ?",
                (token_hash,),
            ).fetchone()
        if row is None:
            return None
        return ResetTokenRow(
            id=row["id"],
            user_id=row["user_id"],
            token_hash=row["token_hash"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            used_at=row["used_at"],
        )

    def mark_used(self, token_id: str, used_at: str) -> bool:
        """Atomically consume a token (single-use, AC-12). Returns True iff THIS call consumed a still-
        unused token — the `used_at IS NULL` guard closes the read-then-write TOCTOU so two concurrent
        redemptions of the same token cannot both succeed (only the first gets True)."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE password_reset_tokens SET used_at = ? WHERE id = ? AND used_at IS NULL",
                (used_at, token_id),
            )
            self._conn.commit()
            return cur.rowcount == 1

    def invalidate_user_tokens(self, user_id: str, used_at: str) -> None:
        """Mark every still-unused token for this user as used (AC-5) — only the newest link survives.
        Scoped to user_id; already-used rows and other users' rows are untouched."""
        with self._lock:
            self._conn.execute(
                "UPDATE password_reset_tokens SET used_at = ? "
                "WHERE user_id = ? AND used_at IS NULL",
                (used_at, user_id),
            )
            self._conn.commit()

    def delete_expired_or_used_for_user(self, user_id: str, now_iso: str) -> None:
        """Opportunistic scoped cleanup (AC-20): delete this user's used or expired token rows."""
        with self._lock:
            self._conn.execute(
                "DELETE FROM password_reset_tokens "
                "WHERE user_id = ? AND (used_at IS NOT NULL OR expires_at < ?)",
                (user_id, now_iso),
            )
            self._conn.commit()
