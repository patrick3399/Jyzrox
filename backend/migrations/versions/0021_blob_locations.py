"""bind external blob locations to images

Revision ID: 0021
Revises: 0020
Create Date: 2026-07-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE blob_locations (
            blob_sha256 TEXT NOT NULL REFERENCES blobs(sha256) ON DELETE CASCADE,
            external_path TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (blob_sha256, external_path)
        )
        """
    )
    op.execute("ALTER TABLE images ADD COLUMN external_path TEXT")
    op.execute(
        """
        INSERT INTO blob_locations (blob_sha256, external_path)
        SELECT sha256, external_path
        FROM blobs
        WHERE external_path IS NOT NULL
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        """
        UPDATE images AS i
        SET external_path = b.external_path
        FROM blobs AS b
        WHERE i.blob_sha256 = b.sha256
          AND b.storage = 'external'
          AND b.external_path IS NOT NULL
        """
    )
    op.execute(
        """
        ALTER TABLE images
        ADD CONSTRAINT fk_images_blob_location
        FOREIGN KEY (blob_sha256, external_path)
        REFERENCES blob_locations(blob_sha256, external_path)
        """
    )
    op.execute(
        """
        CREATE INDEX idx_images_external_path
        ON images(external_path)
        WHERE external_path IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_images_external_path")
    op.execute("ALTER TABLE images DROP CONSTRAINT IF EXISTS fk_images_blob_location")
    op.execute("ALTER TABLE images DROP COLUMN IF EXISTS external_path")
    op.execute("DROP TABLE IF EXISTS blob_locations")
