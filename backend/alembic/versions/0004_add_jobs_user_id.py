"""Add user_id to jobs

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-15

Feature 019 (per-user data isolation): stamp each job with the id of the account that
created it, so reads can be scoped to the owning user. Nullable so pre-019 rows load with
user_id=None (legacy/unowned — hidden from every scoped read, never migrated).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("user_id", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "user_id")
