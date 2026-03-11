"""Add duration column to blobs table (for video support).

Revision ID: 0004
Revises: 0003
Create Date: 2026-03-10
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "blobs",
        sa.Column("duration", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("blobs", "duration")
