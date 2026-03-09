"""Phase 12: pipelines and budget ledger

Revision ID: a1b2c3d4e5f6
Revises: d29768ed705e
Create Date: 2026-03-09 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'd29768ed705e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Pipelines ──────────────────────────────────────────
    op.create_table(
        'pipelines',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('org_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('team_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('repository_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('title', sa.String(500), nullable=False),
        sa.Column('intent', sa.Text(), nullable=False),
        sa.Column('status', sa.String(30), nullable=False, server_default='draft'),
        sa.Column('task_graph', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('estimated_cost_usd', sa.Numeric(12, 6), server_default='0', nullable=True),
        sa.Column('actual_cost_usd', sa.Numeric(12, 6), server_default='0', nullable=True),
        sa.Column('budget_limit_usd', sa.Numeric(12, 6), nullable=False, server_default='10'),
        sa.Column('branch_name', sa.String(200), nullable=False, server_default=''),
        sa.Column('pr_url', sa.Text(), nullable=True),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['team_id'], ['teams.id']),
        sa.ForeignKeyConstraint(['repository_id'], ['repositories.id']),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_pipelines_team_status', 'pipelines', ['team_id', 'status'])
    op.create_index('idx_pipelines_created_at', 'pipelines', ['created_at'])

    # ── Pipeline Tasks ─────────────────────────────────────
    op.create_table(
        'pipeline_tasks',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('pipeline_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('agent_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('title', sa.String(500), nullable=False),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('complexity', sa.String(5), nullable=False, server_default='M'),
        sa.Column('assigned_role', sa.String(50), nullable=False, server_default='engineer'),
        sa.Column('status', sa.String(20), nullable=False, server_default='todo'),
        sa.Column('dependencies', postgresql.ARRAY(sa.Integer()), nullable=False, server_default='{}'),
        sa.Column('integration_hints', postgresql.ARRAY(sa.Text()), nullable=False, server_default='{}'),
        sa.Column('estimated_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('branch_name', sa.String(200), nullable=False, server_default=''),
        sa.Column('result', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['pipeline_id'], ['pipelines.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_ptasks_pipeline', 'pipeline_tasks', ['pipeline_id'])
    op.create_index('idx_ptasks_status', 'pipeline_tasks', ['status'])

    # ── Budget Ledgers ─────────────────────────────────────
    op.create_table(
        'budget_ledgers',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('pipeline_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('org_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('team_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('budget_limit_usd', sa.Numeric(12, 6), nullable=False),
        sa.Column('estimated_cost_usd', sa.Numeric(12, 6), server_default='0', nullable=True),
        sa.Column('actual_cost_usd', sa.Numeric(12, 6), server_default='0', nullable=True),
        sa.Column('status', sa.String(10), nullable=False, server_default='ok'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['pipeline_id'], ['pipelines.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['team_id'], ['teams.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('pipeline_id'),
    )
    op.create_index('idx_budget_ledgers_org', 'budget_ledgers', ['org_id'])

    # ── Budget Entries ─────────────────────────────────────
    op.create_table(
        'budget_entries',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('ledger_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('pipeline_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('pipeline_task_id', sa.Integer(), nullable=True),
        sa.Column('agent_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('model', sa.String(100), nullable=False),
        sa.Column('input_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('output_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('cost_usd', sa.Numeric(12, 6), nullable=False),
        sa.Column('recorded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['ledger_id'], ['budget_ledgers.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['pipeline_id'], ['pipelines.id']),
        sa.ForeignKeyConstraint(['pipeline_task_id'], ['pipeline_tasks.id']),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_budget_entries_pipeline', 'budget_entries', ['pipeline_id'])
    op.create_index('idx_budget_entries_recorded', 'budget_entries', ['recorded_at'])


def downgrade() -> None:
    op.drop_index('idx_budget_entries_recorded', table_name='budget_entries')
    op.drop_index('idx_budget_entries_pipeline', table_name='budget_entries')
    op.drop_table('budget_entries')
    op.drop_index('idx_budget_ledgers_org', table_name='budget_ledgers')
    op.drop_table('budget_ledgers')
    op.drop_index('idx_ptasks_status', table_name='pipeline_tasks')
    op.drop_index('idx_ptasks_pipeline', table_name='pipeline_tasks')
    op.drop_table('pipeline_tasks')
    op.drop_index('idx_pipelines_created_at', table_name='pipelines')
    op.drop_index('idx_pipelines_team_status', table_name='pipelines')
    op.drop_table('pipelines')
