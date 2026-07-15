"""Add name and title to users

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-15

Feature 020 (user profile): capture the account holder's real name (required at signup) and
job title (optional) so the UI can show the logged-in person instead of demo chrome. Both
nullable so pre-020 accounts (014/019) load with name=None (UI falls back to the email local
part); never backfilled.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("name", sa.Text, nullable=True))
    op.add_column("users", sa.Column("title", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("users", "title")
    op.drop_column("users", "name")
