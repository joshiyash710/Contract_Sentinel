"""Uploaded-contract blob storage table (feature 054 durable uploads)

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-30

Feature 054 (uploaded-contract durability on Render's ephemeral disk). Additive, reversible: a new
`upload_blobs` table holding the stored (Fernet-encrypted at rest, feature 036) source contract bytes as a
BLOB, keyed by the upload path string (`document_path`), used by the Turso blob-store backend
(app/blob_store.py) so a job resumed after a container restart can re-read its source. No change to
`users`/`jobs`/`password_reset_tokens`/`report_blobs`. On the local-disk backend the table stays empty
(uploads stay on disk). downgrade() drops it.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "upload_blobs",
        sa.Column("key", sa.Text, primary_key=True),
        sa.Column("data", sa.LargeBinary, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("upload_blobs")
