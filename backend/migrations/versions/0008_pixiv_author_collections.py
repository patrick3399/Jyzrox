"""add source works and stable read anchors

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS gallery_source_items (
            id BIGSERIAL PRIMARY KEY,
            gallery_id BIGINT NOT NULL REFERENCES galleries(id) ON DELETE CASCADE,
            source_item_id TEXT NOT NULL,
            source_item_url TEXT,
            title TEXT,
            published_at TIMESTAMPTZ,
            page_count INTEGER NOT NULL DEFAULT 0,
            source_position INTEGER,
            source_seen_at TIMESTAMPTZ,
            status TEXT NOT NULL DEFAULT 'active',
            metadata_json JSONB NOT NULL DEFAULT '{}',
            CONSTRAINT uq_gallery_source_item UNIQUE (gallery_id, source_item_id),
            CONSTRAINT ck_gallery_source_item_status CHECK (status IN ('active', 'source_missing'))
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_gallery_source_items_gallery_order ON gallery_source_items (gallery_id, source_position)")
    op.execute("ALTER TABLE images ADD COLUMN IF NOT EXISTS source_item_row_id BIGINT REFERENCES gallery_source_items(id) ON DELETE SET NULL")
    op.execute("CREATE INDEX IF NOT EXISTS ix_images_source_item_row_id ON images (source_item_row_id)")
    op.execute("ALTER TABLE read_progress ADD COLUMN IF NOT EXISTS last_image_id BIGINT REFERENCES images(id) ON DELETE SET NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE read_progress DROP COLUMN IF EXISTS last_image_id")
    op.execute("ALTER TABLE images DROP COLUMN IF EXISTS source_item_row_id")
    op.execute("DROP TABLE IF EXISTS gallery_source_items")
