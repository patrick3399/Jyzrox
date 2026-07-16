"""add dataset caption fields

Revision ID: 0013
Revises: 0012
Create Date: 2026-07-16
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE images ADD COLUMN IF NOT EXISTS caption TEXT")
    op.execute("ALTER TABLE datasets ADD COLUMN IF NOT EXISTS tag_threshold REAL NOT NULL DEFAULT 0.35")


def downgrade() -> None:
    op.execute("ALTER TABLE datasets DROP COLUMN IF EXISTS tag_threshold")
    op.execute("ALTER TABLE images DROP COLUMN IF EXISTS caption")
