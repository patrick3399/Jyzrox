"""add local library patterns and gallery source paths

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("galleries", sa.Column("source_path", sa.Text(), nullable=True))
    op.add_column(
        "library_paths",
        sa.Column("pattern", sa.Text(), nullable=False, server_default="{title}"),
    )
    op.add_column(
        "library_paths",
        sa.Column("import_mode", sa.Text(), nullable=False, server_default="link"),
    )


def downgrade() -> None:
    op.drop_column("library_paths", "import_mode")
    op.drop_column("library_paths", "pattern")
    op.drop_column("galleries", "source_path")
