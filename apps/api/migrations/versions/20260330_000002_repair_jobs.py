"""add repair jobs table

Revision ID: 20260330_000002
Revises: 20260330_000001
Create Date: 2026-03-30 16:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260330_000002"
down_revision = "20260330_000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "repair_jobs",
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("job_id"),
    )
    op.create_index("ix_repair_jobs_run_id", "repair_jobs", ["run_id"], unique=False)
    op.create_index("ix_repair_jobs_status", "repair_jobs", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_repair_jobs_status", table_name="repair_jobs")
    op.drop_index("ix_repair_jobs_run_id", table_name="repair_jobs")
    op.drop_table("repair_jobs")
