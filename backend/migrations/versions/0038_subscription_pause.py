"""subscriptions: durable pause state (manual / rate_limited / auth)

Revision ID: 0038
Revises: 0037
Create Date: 2026-11-07
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0038"
down_revision: str | None = "0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Same DDL as db/init.sql; idempotent, one statement per op.execute.


def upgrade() -> None:
    for stmt in (
        "ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS paused_at TIMESTAMPTZ",
        "ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS paused_reason TEXT",
        "ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS paused_until TIMESTAMPTZ",
        "ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS halt_count SMALLINT NOT NULL DEFAULT 0",
        "CREATE INDEX IF NOT EXISTS idx_subscriptions_paused_until "
        "ON subscriptions(paused_until) WHERE paused_reason = 'rate_limited'",
    ):
        op.execute(stmt)


def downgrade() -> None:
    for stmt in (
        "DROP INDEX IF EXISTS idx_subscriptions_paused_until",
        "ALTER TABLE subscriptions DROP COLUMN IF EXISTS halt_count",
        "ALTER TABLE subscriptions DROP COLUMN IF EXISTS paused_until",
        "ALTER TABLE subscriptions DROP COLUMN IF EXISTS paused_reason",
        "ALTER TABLE subscriptions DROP COLUMN IF EXISTS paused_at",
    ):
        op.execute(stmt)
