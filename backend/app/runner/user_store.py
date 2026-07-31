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
from datetime import datetime, timedelta, timezone
from typing import Optional

from cryptography.fernet import InvalidToken

import app.config as _cfg
from app.security import crypto


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
    # Per-user Google Drive connection (feature 031). NULL = not connected.
    # Stored ENCRYPTED at rest (feature 032, W1 — Fernet); decrypted transparently on read so this
    # field always holds plaintext Credentials.to_json() (or None).
    google_oauth_token: Optional[str] = None
    google_email: Optional[str] = None  # connected Google account email, for display
    # Server-side session invalidation (feature 032, W2). Bumped on logout-all / password change;
    # a JWT whose `epoch` claim != this value is rejected by require_auth. Default 0 (legacy rows).
    session_epoch: int = 0


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

    @staticmethod
    def _decrypt_token(raw: Optional[str]) -> Optional[str]:
        """Decrypt a stored google_oauth_token → plaintext (feature 032, W1).

        None → None. A legacy plaintext value (pre-032) is tolerated and returned as-is (AC-5).
        A corrupt / foreign-key value (fails decryption AND isn't a plaintext token) → None, so it is
        treated as "not connected" rather than crashing or leaking garbage (EC-1/EC-2).
        """
        if not raw:
            return None
        try:
            return crypto.decrypt(raw)
        except InvalidToken:
            return raw if crypto.looks_like_plaintext_token(raw) else None

    def _row_to_user(self, row: sqlite3.Row) -> UserRow:
        raw_token = (
            row["google_oauth_token"] if "google_oauth_token" in row.keys() else None
        )
        return UserRow(
            id=row["id"],
            email=row["email"],
            password_hash=row["password_hash"],
            created_at=row["created_at"],
            name=row["name"] if "name" in row.keys() else None,
            title=row["title"] if "title" in row.keys() else None,
            google_oauth_token=self._decrypt_token(raw_token),
            google_email=row["google_email"] if "google_email" in row.keys() else None,
            session_epoch=(
                row["session_epoch"] if "session_epoch" in row.keys() and row["session_epoch"] is not None else 0
            ),
        )

    def get_by_email(self, email: str) -> Optional[UserRow]:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, email, password_hash, created_at, name, title, google_oauth_token, google_email, session_epoch FROM users WHERE email = ?",
                (email,),
            ).fetchone()
        return self._row_to_user(row) if row is not None else None

    def get_by_id(self, user_id: str) -> Optional[UserRow]:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, email, password_hash, created_at, name, title, google_oauth_token, google_email, session_epoch FROM users WHERE id = ?",
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

    # ── Feature 032 (W3): per-account brute-force lockout (persisted; EC-8) ──────
    def record_login_failure(self, email: str) -> None:
        """Record a failed login for `email`. Locks the account after AUTH_LOCKOUT_MAX_FAILURES
        CONSECUTIVE failures within AUTH_LOCKOUT_WINDOW_SECONDS. Unknown email → no-op (AC-16)."""
        now = datetime.now(timezone.utc)
        with self._lock:
            row = self._conn.execute(
                "SELECT failed_login_count, first_failure_at FROM users WHERE email = ?",
                (email,),
            ).fetchone()
            if row is None:
                return  # unknown email — never create a row / never disclose
            count = row["failed_login_count"] or 0
            first_at = row["first_failure_at"]

            within_window = False
            if first_at is not None:
                try:
                    elapsed = (now - datetime.fromisoformat(first_at)).total_seconds()
                    within_window = elapsed <= _cfg.AUTH_LOCKOUT_WINDOW_SECONDS
                except ValueError:
                    within_window = False

            if within_window:
                count += 1
            else:
                count = 1
                first_at = now.isoformat()

            lockout_until = None
            if count >= _cfg.AUTH_LOCKOUT_MAX_FAILURES:
                lockout_until = (
                    now + timedelta(seconds=_cfg.AUTH_LOCKOUT_DURATION_SECONDS)
                ).isoformat()

            self._conn.execute(
                "UPDATE users SET failed_login_count = ?, first_failure_at = ?, lockout_until = ? "
                "WHERE email = ?",
                (count, first_at, lockout_until, email),
            )
            self._conn.commit()

    def reset_login_failures(self, email: str) -> None:
        """Clear failure counter + lockout on a successful login (AC-14). Unknown email → no-op."""
        with self._lock:
            self._conn.execute(
                "UPDATE users SET failed_login_count = 0, first_failure_at = NULL, "
                "lockout_until = NULL WHERE email = ?",
                (email,),
            )
            self._conn.commit()

    def is_locked(self, email: str) -> bool:
        """True if `email` is currently locked out (now < lockout_until). Unknown email → False."""
        with self._lock:
            row = self._conn.execute(
                "SELECT lockout_until FROM users WHERE email = ?", (email,)
            ).fetchone()
        if row is None or row["lockout_until"] is None:
            return False
        try:
            return datetime.now(timezone.utc) < datetime.fromisoformat(row["lockout_until"])
        except ValueError:
            return False

    def bump_session_epoch(self, user_id: str) -> None:
        """Feature 032 (W2): invalidate ALL outstanding sessions for a user (logout-everywhere).

        Increments users.session_epoch; any JWT carrying the old epoch is then rejected by require_auth.
        Called on 'sign out of all devices' and on a password change.
        """
        with self._lock:
            self._conn.execute(
                "UPDATE users SET session_epoch = session_epoch + 1 WHERE id = ?",
                (user_id,),
            )
            self._conn.commit()

    # ── Feature 031: per-user Google Drive credentials (all user_id-scoped) ──────
    def set_google_credentials(
        self, user_id: str, token_json: str, google_email: Optional[str]
    ) -> None:
        """Store (or replace) the connecting account's Google credentials + email.

        The token is ENCRYPTED at rest (feature 032, W1). Empty/None token → SQL NULL (never
        encrypt(""); EC-11).
        """
        encrypted = crypto.encrypt(token_json) if token_json else None
        with self._lock:
            self._conn.execute(
                "UPDATE users SET google_oauth_token = ?, google_email = ? WHERE id = ?",
                (encrypted, google_email, user_id),
            )
            self._conn.commit()

    def get_google_credentials(self, user_id: str) -> Optional[str]:
        """Return the user's DECRYPTED Google credentials JSON, or None if not connected/undecryptable."""
        with self._lock:
            row = self._conn.execute(
                "SELECT google_oauth_token FROM users WHERE id = ?", (user_id,)
            ).fetchone()
        return self._decrypt_token(row["google_oauth_token"]) if row is not None else None

    def get_google_email(self, user_id: str) -> Optional[str]:
        """Return the connected Google account email, or None if not connected."""
        with self._lock:
            row = self._conn.execute(
                "SELECT google_email FROM users WHERE id = ?", (user_id,)
            ).fetchone()
        return row["google_email"] if row is not None else None

    def clear_google_credentials(self, user_id: str) -> None:
        """Disconnect: null out the user's Google credentials + email."""
        with self._lock:
            self._conn.execute(
                "UPDATE users SET google_oauth_token = NULL, google_email = NULL WHERE id = ?",
                (user_id,),
            )
            self._conn.commit()
