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
    # Profile (feature 020). name is required at the API (SignupRequest) but nullable in the
    # store so legacy 014/019 rows load; title is always optional.
    name: Optional[str] = None
    title: Optional[str] = None


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

    def create(
        self,
        email: str,
        password_hash: str,
        name: Optional[str] = None,
        title: Optional[str] = None,
    ) -> UserRow:
        """Insert a new user row and return it.

        Raises EmailExists if the email is already registered (UNIQUE constraint).
        name/title (feature 020) are persisted as-is; the API layer enforces required-name.
        """
        uid = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        try:
            with self._lock:
                self._conn.execute(
                    "INSERT INTO users (id, email, password_hash, created_at, name, title) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (uid, email, password_hash, now, name, title),
                )
                self._conn.commit()
        except sqlite3.IntegrityError as exc:
            raise EmailExists(f"Email already registered: {email!r}") from exc
        return UserRow(
            id=uid, email=email, password_hash=password_hash, created_at=now,
            name=name, title=title,
        )

    def _row_to_user(self, row: sqlite3.Row) -> UserRow:
        return UserRow(
            id=row["id"],
            email=row["email"],
            password_hash=row["password_hash"],
            created_at=row["created_at"],
            name=row["name"] if "name" in row.keys() else None,
            title=row["title"] if "title" in row.keys() else None,
        )

    def get_by_email(self, email: str) -> Optional[UserRow]:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, email, password_hash, created_at, name, title FROM users WHERE email = ?",
                (email,),
            ).fetchone()
        return self._row_to_user(row) if row is not None else None

    def get_by_id(self, user_id: str) -> Optional[UserRow]:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, email, password_hash, created_at, name, title FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        return self._row_to_user(row) if row is not None else None

    def count(self) -> int:
        with self._lock:
            result = self._conn.execute("SELECT COUNT(*) FROM users").fetchone()
        return result[0]

    def update_profile(
        self, user_id: str, name: str, title: Optional[str]
    ) -> Optional[UserRow]:
        """Feature 023: update the user's name/title; return the refreshed row.

        Only name/title are touched — email/id/created_at/password_hash are untouched.
        Returns None only if the user id does not exist (require_auth precludes that at the API).
        """
        with self._lock:
            self._conn.execute(
                "UPDATE users SET name = ?, title = ? WHERE id = ?",
                (name, title, user_id),
            )
            self._conn.commit()
        return self.get_by_id(user_id)

    def update_password(self, user_id: str, new_hash: str) -> None:
        """Feature 023: replace the user's password hash (already hashed by the caller)."""
        with self._lock:
            self._conn.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (new_hash, user_id),
            )
            self._conn.commit()
