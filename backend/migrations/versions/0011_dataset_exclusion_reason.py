"""add dataset image exclusion provenance

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-15
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE dataset_images ADD COLUMN IF NOT EXISTS exclusion_reason TEXT")
    op.execute(
        "UPDATE dataset_images SET exclusion_reason = 'manual' WHERE state = 'excluded' AND exclusion_reason IS NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE dataset_images DROP COLUMN IF EXISTS exclusion_reason")
