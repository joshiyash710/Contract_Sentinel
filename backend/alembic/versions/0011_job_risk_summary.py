"""Denormalized risk summary on the jobs row (feature 066 — kill the dashboard N+1)

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-15

Feature 066: /api/dashboard and /api/jobs read one report BLOB per completed job (O(N) cross-region
round-trips on the Turso deploy → multi-second loads + 500s). This adds a compact risk summary to the
`jobs` row, stamped at completion, so both endpoints build from the single SELECT they already run; rows
without a stored summary (legacy) fall back to reading the report BLOB. Additive + reversible: seven
nullable columns on `jobs` (NULL ⇒ no stored summary ⇒ fallback). No change to other tables. downgrade()
drops them.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INT_COLS = ("risk_high", "risk_medium", "risk_low", "validated_findings", "total_clauses",
             "analysis_degraded")


def upgrade() -> None:
    for name in _INT_COLS:
        op.add_column("jobs", sa.Column(name, sa.Integer, nullable=True))
    op.add_column("jobs", sa.Column("risk_by_type", sa.Text, nullable=True))  # JSON {type:{sev:count}}


def downgrade() -> None:
    op.drop_column("jobs", "risk_by_type")
    for name in reversed(_INT_COLS):
        op.drop_column("jobs", name)
