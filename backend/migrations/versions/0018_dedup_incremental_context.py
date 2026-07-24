"""add incremental dedup state and occurrence context

Revision ID: 0018
Revises: 0017
Create Date: 2026-07-24
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE blobs ADD COLUMN IF NOT EXISTS dedup_scanned_threshold SMALLINT")
    op.execute("ALTER TABLE blob_relationships ADD COLUMN IF NOT EXISTS context_scope TEXT")
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_blobs_dedup_scanned_threshold
        ON blobs(dedup_scanned_threshold)
        WHERE phash_int IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE blobs
        SET media_type = 'video',
            width = NULL,
            height = NULL,
            duration = NULL,
            thumbhash = NULL,
            phash = NULL,
            phash_int = NULL,
            phash_q0 = NULL,
            phash_q1 = NULL,
            phash_q2 = NULL,
            phash_q3 = NULL,
            dedup_scanned_threshold = NULL
        WHERE lower(extension) = '.mov'
          AND media_type <> 'video'
        """
    )
    op.execute(
        """
        UPDATE blob_relationships
        SET relationship = 'same_gallery_only',
            context_scope = 'same_gallery_only'
        WHERE relationship = 'whitelisted'
          AND reason = 'same_gallery_variant'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_blobs_dedup_scanned_threshold")
    op.execute("ALTER TABLE blob_relationships DROP COLUMN IF EXISTS context_scope")
    op.execute("ALTER TABLE blobs DROP COLUMN IF EXISTS dedup_scanned_threshold")
