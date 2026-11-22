"""Immutable prototype artifacts and a local export receipt; no execution."""

import sqlalchemy as sa

from alembic import op

revision = "102_development"
down_revision = "101_planning"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "development_artifacts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("key", sa.String(200), nullable=False, unique=True),
        sa.Column("request", sa.Text(), nullable=False),
        sa.Column("report", sa.Text(), nullable=False),
        sa.Column("export", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("development_artifacts")
