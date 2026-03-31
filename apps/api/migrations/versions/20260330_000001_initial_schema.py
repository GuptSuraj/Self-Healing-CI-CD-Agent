"""initial schema

Revision ID: 20260330_000001
Revises: None
Create Date: 2026-03-30 15:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260330_000001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "repair_runs",
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("repository", sa.String(length=255), nullable=False),
        sa.Column("workflow_run_id", sa.Integer(), nullable=False),
        sa.Column("workflow_name", sa.String(length=255), nullable=False),
        sa.Column("sha", sa.String(length=64), nullable=False),
        sa.Column("branch", sa.String(length=255), nullable=False),
        sa.Column("failed_job", sa.String(length=255), nullable=False),
        sa.Column("failed_step", sa.String(length=255), nullable=False),
        sa.Column("log_excerpt", sa.Text(), nullable=False),
        sa.Column("html_url", sa.Text(), nullable=True),
        sa.Column("context_json", sa.JSON(), nullable=False),
        sa.Column("analysis_json", sa.JSON(), nullable=True),
        sa.Column("patch_json", sa.JSON(), nullable=True),
        sa.Column("validation_json", sa.JSON(), nullable=True),
        sa.Column("confidence_json", sa.JSON(), nullable=True),
        sa.Column("pull_request_json", sa.JSON(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("run_id"),
    )
    op.create_index("ix_repair_runs_status", "repair_runs", ["status"], unique=False)
    op.create_index("ix_repair_runs_category", "repair_runs", ["category"], unique=False)
    op.create_index("ix_repair_runs_repository", "repair_runs", ["repository"], unique=False)
    op.create_index("ix_repair_runs_workflow_run_id", "repair_runs", ["workflow_run_id"], unique=False)
    op.create_index("ix_repair_runs_sha", "repair_runs", ["sha"], unique=False)

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["repair_runs.run_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_events_run_id", "audit_events", ["run_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_audit_events_run_id", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_repair_runs_sha", table_name="repair_runs")
    op.drop_index("ix_repair_runs_workflow_run_id", table_name="repair_runs")
    op.drop_index("ix_repair_runs_repository", table_name="repair_runs")
    op.drop_index("ix_repair_runs_category", table_name="repair_runs")
    op.drop_index("ix_repair_runs_status", table_name="repair_runs")
    op.drop_table("repair_runs")
