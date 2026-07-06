"""novel module: read progress + user prefs

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-05

Additive, idempotent DDL — safe to run against a DB already provisioned by
db/init.sql (BE-T15). Adds the novel_read_progress table and users.novel_prefs.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS novel_prefs JSONB NOT NULL DEFAULT '{}'::jsonb")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS novel_read_progress (
            user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            file_path  TEXT   NOT NULL,
            position   TEXT   NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (user_id, file_path)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS novel_read_progress")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS novel_prefs")
