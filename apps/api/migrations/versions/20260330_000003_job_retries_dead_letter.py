"""add job retries and dead letter state

Revision ID: 20260330_000003
Revises: 20260330_000002
Create Date: 2026-03-30 17:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260330_000003"
down_revision = "20260330_000002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "repair_jobs",
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "repair_jobs",
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
    )


def downgrade() -> None:
    op.drop_column("repair_jobs", "max_attempts")
    op.drop_column("repair_jobs", "attempts")
