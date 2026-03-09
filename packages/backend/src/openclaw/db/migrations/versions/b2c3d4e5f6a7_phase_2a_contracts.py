"""Phase 2A: contracts table and pipeline contracts column

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-03-09 16:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Contracts table ─────────────────────────────────────
    op.create_table(
        'contracts',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('pipeline_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('pipeline_task_id', sa.Integer(), nullable=True),
        sa.Column('contract_type', sa.String(30), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('specification', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('locked', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('locked_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('locked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['pipeline_id'], ['pipelines.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['pipeline_task_id'], ['pipeline_tasks.id']),
        sa.ForeignKeyConstraint(['locked_by'], ['agents.id']),
    )
    op.create_index('idx_contracts_pipeline', 'contracts', ['pipeline_id'])
    op.create_index('idx_contracts_type', 'contracts', ['contract_type'])

    # ── Add contracts JSONB column to pipelines ─────────────
    op.add_column(
        'pipelines',
        sa.Column('contracts', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('pipelines', 'contracts')
    op.drop_index('idx_contracts_type', 'contracts')
    op.drop_index('idx_contracts_pipeline', 'contracts')
    op.drop_table('contracts')
