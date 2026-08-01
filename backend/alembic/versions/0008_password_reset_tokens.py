"""Password-reset tokens table (feature 034 forgot-password)

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-01

Feature 034 (forgot-password). Additive, reversible: a new `password_reset_tokens` table holding
single-use, time-limited, HMAC-hashed reset tokens (the raw token lives only in the emailed link).
No change to `users` or `jobs`. downgrade() drops the indexes + table.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("user_id", sa.Text, nullable=False),
        sa.Column("token_hash", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("expires_at", sa.Text, nullable=False),
        sa.Column("used_at", sa.Text, nullable=True),
    )
    op.create_index("ix_prt_token_hash", "password_reset_tokens", ["token_hash"])
    op.create_index("ix_prt_user_id", "password_reset_tokens", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_prt_user_id", table_name="password_reset_tokens")
    op.drop_index("ix_prt_token_hash", table_name="password_reset_tokens")
    op.drop_table("password_reset_tokens")
