"""archive table for the bundled xiuren7 gallery-dl extractor

Revision ID: 0031
Revises: 0030
Create Date: 2026-10-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # gallery-dl would create a missing archive table as (entry) only, without
    # the gallery_id FK that ties entries to a gallery's lifecycle.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS xiuren7 (
            entry       TEXT PRIMARY KEY,
            gallery_id  BIGINT REFERENCES galleries(id) ON DELETE CASCADE,
            job_id      UUID,
            created_at  TIMESTAMPTZ DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_xiuren7_unlinked ON xiuren7 (job_id) WHERE gallery_id IS NULL")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS xiuren7")
