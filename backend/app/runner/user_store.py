"""
Thread-safe SQLite user store for feature 014 single-user auth gate.

Mirrors the lock discipline and connection pattern of JobStore (feature 012).
Schema is owned by Alembic migration 0003 — this class assumes upgrade_to_head
has already run. All email normalization (trim + lower) must be done by the caller
before calling create() / get_by_email() (EC-2).
"""

import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


class EmailExists(Exception):
    """Raised by UserStore.create() when the email is already registered."""


@dataclass
class UserRow:
    id: str
    email: str
    password_hash: str
    created_at: str


class UserStore:
    """Thread-safe synchronous SQLite user store.

    One shared sqlite3 connection with check_same_thread=False, guarded by a lock,
    mirroring JobStore's pattern (spec D17 / plan §3.3).
    """

    def __init__(self, db_path: str) -> None:
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def create(self, email: str, password_hash: str) -> UserRow:
        """Insert a new user row and return it.

        Raises EmailExists if the email is already registered (UNIQUE constraint).
        """
        uid = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        try:
            with self._lock:
                self._conn.execute(
                    "INSERT INTO users (id, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
                    (uid, email, password_hash, now),
                )
                self._conn.commit()
        except sqlite3.IntegrityError as exc:
            raise EmailExists(f"Email already registered: {email!r}") from exc
        return UserRow(id=uid, email=email, password_hash=password_hash, created_at=now)

    def get_by_email(self, email: str) -> Optional[UserRow]:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, email, password_hash, created_at FROM users WHERE email = ?",
                (email,),
            ).fetchone()
        if row is None:
            return None
        return UserRow(
            id=row["id"],
            email=row["email"],
            password_hash=row["password_hash"],
            created_at=row["created_at"],
        )

    def get_by_id(self, user_id: str) -> Optional[UserRow]:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, email, password_hash, created_at FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        return UserRow(
            id=row["id"],
            email=row["email"],
            password_hash=row["password_hash"],
            created_at=row["created_at"],
        )

    def count(self) -> int:
        with self._lock:
            result = self._conn.execute("SELECT COUNT(*) FROM users").fetchone()
        return result[0]
