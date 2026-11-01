"""allow link pages to exist before they are hashed

Revision ID: 0027
Revises: 0026
Create Date: 2026-10-07
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A pending link page has an external_path and no blob yet (ADR 0015).
    op.execute("ALTER TABLE images ALTER COLUMN blob_sha256 DROP NOT NULL")
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_images_blob_or_external_path') THEN
                ALTER TABLE images ADD CONSTRAINT ck_images_blob_or_external_path
                    CHECK (blob_sha256 IS NOT NULL OR external_path IS NOT NULL);
            END IF;
        END $$
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_images_pending ON images (gallery_id) WHERE blob_sha256 IS NULL")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_images_pending")
    op.execute("ALTER TABLE images DROP CONSTRAINT IF EXISTS ck_images_blob_or_external_path")
    # Pending pages cannot satisfy NOT NULL; they are re-registered by the next sync.
    op.execute("DELETE FROM images WHERE blob_sha256 IS NULL")
    op.execute("ALTER TABLE images ALTER COLUMN blob_sha256 SET NOT NULL")
