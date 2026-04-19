"""add passed_failed_samples to eval_runs

Revision ID: b7e4a2f1c530
Revises: a3f2c1d8e901
Create Date: 2026-04-19 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b7e4a2f1c530"
down_revision = "a3f2c1d8e901"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "eval_runs", sa.Column("passed_samples", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "eval_runs", sa.Column("failed_samples", sa.Integer(), nullable=False, server_default="0")
    )


def downgrade() -> None:
    op.drop_column("eval_runs", "failed_samples")
    op.drop_column("eval_runs", "passed_samples")
