"""add image visibility and source sync state

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-29
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Idempotent so `alembic upgrade head` is safe even when db/init.sql has
    # already created these objects (see scripts/bootstrap_db.py, issue #55).
    op.execute("ALTER TABLE images ADD COLUMN IF NOT EXISTS visibility TEXT NOT NULL DEFAULT 'active'")
    op.execute("ALTER TABLE images ADD COLUMN IF NOT EXISTS source_item_id TEXT")
    op.execute("ALTER TABLE images ADD COLUMN IF NOT EXISTS source_item_url TEXT")
    op.execute("ALTER TABLE images ADD COLUMN IF NOT EXISTS source_position INTEGER")
    op.execute("ALTER TABLE images ADD COLUMN IF NOT EXISTS source_seen_at TIMESTAMPTZ")
    op.execute("ALTER TABLE images ADD COLUMN IF NOT EXISTS hidden_at TIMESTAMPTZ")
    op.execute("ALTER TABLE images ADD COLUMN IF NOT EXISTS replaced_by_image_id BIGINT")
    op.execute(
        """
        DO $$ BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'fk_images_replaced_by_image_id'
          ) THEN
            ALTER TABLE images ADD CONSTRAINT fk_images_replaced_by_image_id
              FOREIGN KEY (replaced_by_image_id) REFERENCES images (id) ON DELETE SET NULL;
          END IF;
        END $$;
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_images_visibility ON images (visibility)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_images_source_item ON images (gallery_id, source_item_id)")

    op.execute("ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS last_success_at TIMESTAMPTZ")


def downgrade() -> None:
    op.execute("ALTER TABLE subscriptions DROP COLUMN IF EXISTS last_success_at")
    op.execute("DROP INDEX IF EXISTS idx_images_source_item")
    op.execute("DROP INDEX IF EXISTS idx_images_visibility")
    op.execute("ALTER TABLE images DROP CONSTRAINT IF EXISTS fk_images_replaced_by_image_id")
    op.execute("ALTER TABLE images DROP COLUMN IF EXISTS replaced_by_image_id")
    op.execute("ALTER TABLE images DROP COLUMN IF EXISTS hidden_at")
    op.execute("ALTER TABLE images DROP COLUMN IF EXISTS source_seen_at")
    op.execute("ALTER TABLE images DROP COLUMN IF EXISTS source_position")
    op.execute("ALTER TABLE images DROP COLUMN IF EXISTS source_item_url")
    op.execute("ALTER TABLE images DROP COLUMN IF EXISTS source_item_id")
    op.execute("ALTER TABLE images DROP COLUMN IF EXISTS visibility")
