"""Rename pipeline to run across all tables and columns.

Revision ID: g7h8i9j0k1l2
Revises: f6a7b8c9d0e1
Create Date: 2026-03-10 00:00:00.000000
"""

from alembic import op

revision = "g7h8i9j0k1l2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Rename tables ---
    op.rename_table("pipelines", "runs")
    op.rename_table("pipeline_tasks", "run_tasks")

    # --- Rename columns: pipeline_id -> run_id ---
    op.alter_column("run_tasks", "pipeline_id", new_column_name="run_id")
    op.alter_column("contracts", "pipeline_id", new_column_name="run_id")
    op.alter_column("budget_ledgers", "pipeline_id", new_column_name="run_id")
    op.alter_column("budget_entries", "pipeline_id", new_column_name="run_id")
    op.alter_column("sandbox_runs", "pipeline_id", new_column_name="run_id")

    # --- Rename columns: pipeline_task_id -> run_task_id ---
    op.alter_column("contracts", "pipeline_task_id", new_column_name="run_task_id")
    op.alter_column("budget_entries", "pipeline_task_id", new_column_name="run_task_id")
    op.alter_column("sandbox_runs", "pipeline_task_id", new_column_name="run_task_id")
    op.alter_column("security_audit", "pipeline_task_id", new_column_name="run_task_id")

    # --- Rename indexes ---
    op.execute(
        "ALTER INDEX IF EXISTS idx_pipelines_team_status "
        "RENAME TO idx_runs_team_status"
    )
    op.execute(
        "ALTER INDEX IF EXISTS idx_pipelines_created_at "
        "RENAME TO idx_runs_created_at"
    )
    op.execute("ALTER INDEX IF EXISTS idx_ptasks_pipeline RENAME TO idx_rtasks_run")
    op.execute("ALTER INDEX IF EXISTS idx_ptasks_status RENAME TO idx_rtasks_status")
    op.execute(
        "ALTER INDEX IF EXISTS idx_contracts_pipeline "
        "RENAME TO idx_contracts_run"
    )
    op.execute(
        "ALTER INDEX IF EXISTS idx_budget_entries_pipeline "
        "RENAME TO idx_budget_entries_run"
    )
    op.execute(
        "ALTER INDEX IF EXISTS idx_sandbox_runs_pipeline_task "
        "RENAME TO idx_sandbox_runs_run_task"
    )


def downgrade() -> None:
    # --- Reverse index renames ---
    op.execute(
        "ALTER INDEX IF EXISTS idx_runs_team_status "
        "RENAME TO idx_pipelines_team_status"
    )
    op.execute(
        "ALTER INDEX IF EXISTS idx_runs_created_at "
        "RENAME TO idx_pipelines_created_at"
    )
    op.execute("ALTER INDEX IF EXISTS idx_rtasks_run RENAME TO idx_ptasks_pipeline")
    op.execute("ALTER INDEX IF EXISTS idx_rtasks_status RENAME TO idx_ptasks_status")
    op.execute(
        "ALTER INDEX IF EXISTS idx_contracts_run "
        "RENAME TO idx_contracts_pipeline"
    )
    op.execute(
        "ALTER INDEX IF EXISTS idx_budget_entries_run "
        "RENAME TO idx_budget_entries_pipeline"
    )
    op.execute(
        "ALTER INDEX IF EXISTS idx_sandbox_runs_run_task "
        "RENAME TO idx_sandbox_runs_pipeline_task"
    )

    # --- Reverse pipeline_task_id renames ---
    op.alter_column("security_audit", "run_task_id", new_column_name="pipeline_task_id")
    op.alter_column("sandbox_runs", "run_task_id", new_column_name="pipeline_task_id")
    op.alter_column("budget_entries", "run_task_id", new_column_name="pipeline_task_id")
    op.alter_column("contracts", "run_task_id", new_column_name="pipeline_task_id")

    # --- Reverse pipeline_id renames ---
    op.alter_column("sandbox_runs", "run_id", new_column_name="pipeline_id")
    op.alter_column("budget_entries", "run_id", new_column_name="pipeline_id")
    op.alter_column("budget_ledgers", "run_id", new_column_name="pipeline_id")
    op.alter_column("contracts", "run_id", new_column_name="pipeline_id")
    op.alter_column("run_tasks", "run_id", new_column_name="pipeline_id")

    # --- Reverse table renames ---
    op.rename_table("run_tasks", "pipeline_tasks")
    op.rename_table("runs", "pipelines")
