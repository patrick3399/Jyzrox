"""add local library patterns and gallery source paths

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-25
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Idempotent so `alembic upgrade head` is safe even when db/init.sql has
    # already created these columns (see scripts/bootstrap_db.py, issue #55).
    op.execute("ALTER TABLE galleries ADD COLUMN IF NOT EXISTS source_path TEXT")
    op.execute("ALTER TABLE library_paths ADD COLUMN IF NOT EXISTS pattern TEXT NOT NULL DEFAULT '{title}'")
    op.execute("ALTER TABLE library_paths ADD COLUMN IF NOT EXISTS import_mode TEXT NOT NULL DEFAULT 'link'")


def downgrade() -> None:
    op.execute("ALTER TABLE library_paths DROP COLUMN IF EXISTS import_mode")
    op.execute("ALTER TABLE library_paths DROP COLUMN IF EXISTS pattern")
    op.execute("ALTER TABLE galleries DROP COLUMN IF EXISTS source_path")
