"""persist authoritative source page totals

Revision ID: 0020
Revises: 0019
Create Date: 2026-07-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE galleries ADD COLUMN IF NOT EXISTS source_pages INT")
    op.execute(
        """
        ALTER TABLE galleries
        ADD CONSTRAINT chk_galleries_source_pages_nonnegative
        CHECK (source_pages IS NULL OR source_pages >= 0)
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE galleries DROP CONSTRAINT IF EXISTS chk_galleries_source_pages_nonnegative")
    op.execute("ALTER TABLE galleries DROP COLUMN IF EXISTS source_pages")
