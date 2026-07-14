"""Create users table for single-user auth gate (feature 014).

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-14

Feature 014 (auth-landing): adds the users table to job_store.db (D17 — same DB as
jobs). Stores email/password-hash accounts for the single-user access gate. No
per-user scoping of existing data (D4 — shared space).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Text, primary_key=True, nullable=False),
        sa.Column("email", sa.Text, unique=True, nullable=False),
        sa.Column("password_hash", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("users")
