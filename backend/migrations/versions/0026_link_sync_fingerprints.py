"""add link-sync fingerprints: per-image size/mtime and per-gallery directory mtime

Revision ID: 0026
Revises: 0025
Create Date: 2026-10-07
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nullable on purpose: existing link images have no fingerprint yet. The
    # first link sync adopts the current stat for them without re-hashing.
    op.execute("ALTER TABLE images ADD COLUMN IF NOT EXISTS source_size BIGINT")
    op.execute("ALTER TABLE images ADD COLUMN IF NOT EXISTS source_mtime_ns BIGINT")
    op.execute("ALTER TABLE galleries ADD COLUMN IF NOT EXISTS source_dir_mtime_ns BIGINT")


def downgrade() -> None:
    op.execute("ALTER TABLE galleries DROP COLUMN IF EXISTS source_dir_mtime_ns")
    op.execute("ALTER TABLE images DROP COLUMN IF EXISTS source_mtime_ns")
    op.execute("ALTER TABLE images DROP COLUMN IF EXISTS source_size")
