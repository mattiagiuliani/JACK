"""Execution planning audit only; no executable tasks or expenses."""

import sqlalchemy as sa

from alembic import op

revision = "101_planning"
down_revision = "098_decisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "execution_plans",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("key", sa.String(200), nullable=False, unique=True),
        sa.Column("request", sa.Text(), nullable=False),
        sa.Column("report", sa.Text(), nullable=False),
        sa.Column("review", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("execution_plans")
