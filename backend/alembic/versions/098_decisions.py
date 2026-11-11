"""Persist advisory decisions and one immutable human review."""

import sqlalchemy as sa

from alembic import op

revision = "098_decisions"
down_revision = "097_portfolio"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "portfolio_decisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("key", sa.String(200), nullable=False, unique=True),
        sa.Column("request", sa.Text(), nullable=False),
        sa.Column("report", sa.Text(), nullable=False),
        sa.Column("review", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("portfolio_decisions")
