"""download job mode and stop-and-keep request marker

Revision ID: 0036
Revises: 0035
Create Date: 2026-10-30
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0036"
down_revision: str | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Same DDL as db/init.sql; every statement is idempotent so upgrading a schema
# that init.sql already built is a no-op. One statement per op.execute: asyncpg
# prepares each call and rejects multiple commands in one statement.
#
# mode: how the job was started (download / subscription_initial /
#   subscription_incremental / repair). Existing rows default to 'download';
#   the worker maps legacy options (force_full_scan) to a mode at run time.
# stop_requested_at: set when the user asks to stop and keep what was already
#   imported; NULL means no stop was requested.


def upgrade() -> None:
    op.execute("ALTER TABLE download_jobs ADD COLUMN IF NOT EXISTS mode TEXT NOT NULL DEFAULT 'download'")
    op.execute("ALTER TABLE download_jobs ADD COLUMN IF NOT EXISTS stop_requested_at TIMESTAMPTZ")


def downgrade() -> None:
    op.execute("ALTER TABLE download_jobs DROP COLUMN IF EXISTS stop_requested_at")
    op.execute("ALTER TABLE download_jobs DROP COLUMN IF EXISTS mode")
