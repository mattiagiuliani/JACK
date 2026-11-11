"""Business portfolio foundation.

Revision ID: 097_portfolio
Revises: 9037f069938f
"""

import sqlalchemy as sa

from alembic import op

revision = "097_portfolio"
down_revision = "9037f069938f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ventures",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("snapshot", sa.Text(), nullable=False),
    )
    op.create_table(
        "portfolio_events",
        sa.Column("id", sa.String(200), primary_key=True),
        sa.Column(
            "venture_id", sa.String(36), sa.ForeignKey("ventures.id"), nullable=False
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("request", sa.Text(), nullable=False),
        sa.Column("event", sa.Text(), nullable=False),
        sa.UniqueConstraint("venture_id", "version"),
    )
    op.create_index(
        "ix_portfolio_events_venture_id", "portfolio_events", ["venture_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_portfolio_events_venture_id", table_name="portfolio_events")
    op.drop_table("portfolio_events")
    op.drop_table("ventures")
