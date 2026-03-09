"""Phase 3D: security_audit table.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2025-01-01 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "security_audit",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column(
            "agent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agents.id"),
            nullable=False,
        ),
        sa.Column(
            "team_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("teams.id"),
            nullable=False,
        ),
        sa.Column(
            "pipeline_task_id",
            sa.Integer(),
            sa.ForeignKey("pipeline_tasks.id"),
            nullable=True,
        ),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("rule", sa.String(200), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_security_audit_team_created",
        "security_audit",
        ["team_id", "created_at"],
    )
    op.create_index(
        "idx_security_audit_agent_created",
        "security_audit",
        ["agent_id", "created_at"],
    )
    op.create_index(
        "idx_security_audit_kind",
        "security_audit",
        ["kind"],
    )


def downgrade() -> None:
    op.drop_index("idx_security_audit_kind", table_name="security_audit")
    op.drop_index("idx_security_audit_agent_created", table_name="security_audit")
    op.drop_index("idx_security_audit_team_created", table_name="security_audit")
    op.drop_table("security_audit")
