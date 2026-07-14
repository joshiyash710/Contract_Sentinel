"""Add original_filename to jobs

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-14

Feature 018 (dynamic dashboard): persist the real uploaded filename so the job list /
Activity Feed can show real contract names (001 already declares original_filename;
the runner previously lost it by saving uploads as {job_id}{ext}). Nullable so pre-018
rows load with original_filename=None (list falls back to the job-id name).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("original_filename", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "original_filename")
