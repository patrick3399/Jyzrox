"""persist per-job and per-subscription download policies

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE download_jobs ADD COLUMN IF NOT EXISTS options JSONB NOT NULL DEFAULT '{}'")
    op.execute("ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS download_options JSONB NOT NULL DEFAULT '{}'")


def downgrade() -> None:
    op.execute("ALTER TABLE subscriptions DROP COLUMN IF EXISTS download_options")
    op.execute("ALTER TABLE download_jobs DROP COLUMN IF EXISTS options")
