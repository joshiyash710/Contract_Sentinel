"""Add per-user Google OAuth token to users

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-28

Feature 031 (per-user Google Drive delivery): each account may connect its own Google
account so its reports save to that user's own Drive. Store the user's authorized-user
credentials JSON (refresh token) + the connected Google email. Both nullable — NULL means
"not connected". Stored unencrypted (amendment-authorized Phase-2-DEFERRED interim posture).
Never backfilled; pre-031 accounts load with google_oauth_token=None (not connected).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("google_oauth_token", sa.Text, nullable=True))
    op.add_column("users", sa.Column("google_email", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("users", "google_email")
    op.drop_column("users", "google_oauth_token")
