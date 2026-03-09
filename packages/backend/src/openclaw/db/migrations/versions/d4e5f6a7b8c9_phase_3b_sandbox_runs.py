"""Phase 3B: sandbox_runs table

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-03-09 20:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'sandbox_runs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('sandbox_id', sa.String(50), nullable=False),
        sa.Column('pipeline_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('pipeline_task_id', sa.Integer(), nullable=True),
        sa.Column('team_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('test_cmd', sa.Text(), nullable=False),
        sa.Column('exit_code', sa.Integer(), nullable=True),
        sa.Column('stdout', sa.Text(), nullable=False, server_default=''),
        sa.Column('stderr', sa.Text(), nullable=False, server_default=''),
        sa.Column('passed', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('duration_seconds', sa.Numeric(10, 2), nullable=False, server_default='0'),
        sa.Column('image', sa.String(200), nullable=False, server_default='python:3.12-slim'),
        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('sandbox_id'),
        sa.ForeignKeyConstraint(['pipeline_id'], ['pipelines.id']),
        sa.ForeignKeyConstraint(['pipeline_task_id'], ['pipeline_tasks.id']),
        sa.ForeignKeyConstraint(['team_id'], ['teams.id']),
    )
    op.create_index('idx_sandbox_runs_pipeline_task', 'sandbox_runs', ['pipeline_task_id'])
    op.create_index('idx_sandbox_runs_team', 'sandbox_runs', ['team_id'])


def downgrade() -> None:
    op.drop_index('idx_sandbox_runs_team', table_name='sandbox_runs')
    op.drop_index('idx_sandbox_runs_pipeline_task', table_name='sandbox_runs')
    op.drop_table('sandbox_runs')
