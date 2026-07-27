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

# Backfill is per-Image, not per-Blob. ``Blob.external_path`` holds ONE path per
# sha256, so binding every Image of a shared hash to it collapses genuinely
# distinct source files onto one location (measured on the live DB before this
# migration ran: 142 images across 136 hashes whose own file lives elsewhere —
# in every one of those the legacy path was outside the gallery's own
# source_path). Link-mode imports store the file at
# ``Gallery.source_path + '/' + Image.filename``, so that is the authoritative
# per-Image location; the legacy scalar is only a fallback for rows that cannot
# be reconstructed.
#
# Deliberately portable SQL (correlated subqueries, no UPDATE ... FROM) so
# ``tests/test_blob_location_backfill.py`` can execute these exact statements.
_DERIVED_PATH = "(SELECT g.source_path || '/' || images.filename FROM galleries g WHERE g.id = images.gallery_id)"

_IS_EXTERNAL = "EXISTS (SELECT 1 FROM blobs b WHERE b.sha256 = images.blob_sha256 AND b.storage = 'external')"

_HAS_DERIVED = (
    "images.filename IS NOT NULL AND EXISTS ("
    "SELECT 1 FROM galleries g WHERE g.id = images.gallery_id AND g.source_path IS NOT NULL)"
)

BACKFILL_STATEMENTS: tuple[str, ...] = (
    # 1. Register every reconstructable per-Image location.
    f"""
    INSERT INTO blob_locations (blob_sha256, external_path)
    SELECT images.blob_sha256, {_DERIVED_PATH}
    FROM images
    WHERE {_IS_EXTERNAL} AND {_HAS_DERIVED}
    ON CONFLICT DO NOTHING
    """,
    # 2. Register the legacy scalar paths too, so the fallback in step 4 has a
    #    parent row for the FK.
    """
    INSERT INTO blob_locations (blob_sha256, external_path)
    SELECT sha256, external_path
    FROM blobs
    WHERE external_path IS NOT NULL
    ON CONFLICT DO NOTHING
    """,
    # 3. Bind each Image to its own file.
    f"""
    UPDATE images
    SET external_path = {_DERIVED_PATH}
    WHERE {_IS_EXTERNAL} AND {_HAS_DERIVED}
    """,
    # 4. Only rows with no reconstructable path fall back to the legacy scalar.
    """
    UPDATE images
    SET external_path = (
        SELECT b.external_path FROM blobs b WHERE b.sha256 = images.blob_sha256
    )
    WHERE images.external_path IS NULL
      AND EXISTS (
        SELECT 1 FROM blobs b
        WHERE b.sha256 = images.blob_sha256
          AND b.storage = 'external'
          AND b.external_path IS NOT NULL
      )
    """,
)


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
    for statement in BACKFILL_STATEMENTS:
        op.execute(statement)
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
