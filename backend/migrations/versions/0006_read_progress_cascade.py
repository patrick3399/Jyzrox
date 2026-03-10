"""Add ON DELETE CASCADE to read_progress.gallery_id foreign key.

Revision ID: 0006
Revises: 0005
Create Date: 2026-03-10
"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the existing FK constraint (auto-named by PostgreSQL from init.sql)
    op.drop_constraint(
        "read_progress_gallery_id_fkey",
        "read_progress",
        type_="foreignkey",
    )
    # Re-create with ON DELETE CASCADE
    op.create_foreign_key(
        "read_progress_gallery_id_fkey",
        "read_progress",
        "galleries",
        ["gallery_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    # Drop the cascade FK and restore the plain FK
    op.drop_constraint(
        "read_progress_gallery_id_fkey",
        "read_progress",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "read_progress_gallery_id_fkey",
        "read_progress",
        "galleries",
        ["gallery_id"],
        ["id"],
    )
