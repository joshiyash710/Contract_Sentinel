"""Security hardening Tier 1 — session/lockout columns + OAuth-token encryption backfill

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-31

Feature 032 (security Tier 1). Single consolidated migration:
  DDL (additive, reversible):
    - users.session_epoch       — W2 server-side session invalidation (logout-all / password change)
    - users.failed_login_count  — W3 per-account lockout counter
    - users.first_failure_at    — W3 anchors the consecutive-failure window (ISO string, nullable)
    - users.lockout_until       — W3 lockout expiry (ISO string, nullable)
  Data (idempotent):
    - encrypt any LEGACY plaintext users.google_oauth_token in place (W1). Values already encrypted or
      NULL are skipped (no double-encryption). Authorized by the constitution §2 amendment (2026-07-31).

downgrade() drops the four columns; it does NOT decrypt token values (a true rollback would need the
key, which is out of scope).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── DDL: additive columns ────────────────────────────────────────────────
    op.add_column(
        "users",
        sa.Column("session_epoch", sa.Integer, nullable=False, server_default="0"),
    )
    op.add_column(
        "users",
        sa.Column("failed_login_count", sa.Integer, nullable=False, server_default="0"),
    )
    op.add_column("users", sa.Column("first_failure_at", sa.Text, nullable=True))
    op.add_column("users", sa.Column("lockout_until", sa.Text, nullable=True))

    # ── Data: idempotent encrypt-backfill of legacy plaintext OAuth tokens ────
    # Imported here (not at module top) so the migration only touches crypto when it actually runs,
    # and picks up any test-time config/key overrides.
    from app.security import crypto

    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, google_oauth_token FROM users WHERE google_oauth_token IS NOT NULL"
        )
    ).fetchall()
    for uid, token in rows:
        # Only re-encrypt values that are still LEGACY PLAINTEXT (a parseable token JSON). A value that
        # is already Fernet ciphertext is not a plaintext token → skipped → no double-encryption.
        if token and crypto.looks_like_plaintext_token(token):
            bind.execute(
                sa.text("UPDATE users SET google_oauth_token = :t WHERE id = :id"),
                {"t": crypto.encrypt(token), "id": uid},
            )


def downgrade() -> None:
    op.drop_column("users", "lockout_until")
    op.drop_column("users", "first_failure_at")
    op.drop_column("users", "failed_login_count")
    op.drop_column("users", "session_epoch")
