"""Create jobs table

Revision ID: 0001
Revises:
Create Date: 2026-07-09

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("job_id", sa.Text, primary_key=True),
        sa.Column("document_path", sa.Text, nullable=False),
        sa.Column("recipient", sa.Text, nullable=True),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("submitted_at", sa.Text, nullable=False),
        sa.Column("started_at", sa.Text, nullable=True),
        sa.Column("finished_at", sa.Text, nullable=True),
        sa.Column("current_node", sa.Text, nullable=True),
        sa.Column("completed_nodes", sa.Text, nullable=False, server_default="[]"),
        sa.Column("report_path", sa.Text, nullable=True),
        sa.Column("mcp_delivery_status", sa.Text, nullable=False, server_default="{}"),
        sa.Column("error", sa.Text, nullable=True),
    )
    op.create_index("ix_jobs_submitted_at", "jobs", ["submitted_at"])


def downgrade() -> None:
    op.drop_index("ix_jobs_submitted_at", table_name="jobs")
    op.drop_table("jobs")
