"""Report blob storage table (feature 052 Turso blob storage)

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-29

Feature 052 (report durability on Render's ephemeral disk). Additive, reversible: a new `report_blobs`
table holding the durable report artifacts (.json/.md) as BLOBs, keyed by the report path string, used
by the Turso blob-store backend (app/blob_store.py). No change to `users`/`jobs`/`password_reset_tokens`.
On the local-disk backend the table simply stays empty (reports stay on disk). downgrade() drops it.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "report_blobs",
        sa.Column("key", sa.Text, primary_key=True),
        sa.Column("data", sa.LargeBinary, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("report_blobs")
