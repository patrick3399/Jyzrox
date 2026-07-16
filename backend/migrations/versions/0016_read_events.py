"""add reading event history

Revision ID: 0016
Revises: 0015
Create Date: 2026-07-16
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS read_events (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            gallery_id BIGINT NOT NULL REFERENCES galleries(id) ON DELETE CASCADE,
            image_id BIGINT REFERENCES images(id) ON DELETE SET NULL,
            page_num INTEGER NOT NULL,
            duration_ms INTEGER,
            occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_read_events_user_time ON read_events (user_id, occurred_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_read_events_gallery ON read_events (gallery_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS read_events")
