"""Add phash column to images table.

Revision ID: 0003
Revises: 0002
Create Date: 2026-03-09
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("images", sa.Column("phash", sa.Text(), nullable=True))
    op.create_index(
        "idx_images_phash",
        "images",
        ["phash"],
        postgresql_where=sa.text("phash IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_images_phash", table_name="images")
    op.drop_column("images", "phash")
