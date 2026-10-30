"""galleries.content_updated_at: last time active pages grew

Revision ID: 0037
Revises: 0036
Create Date: 2026-10-30
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0037"
down_revision: str | None = "0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Same DDL as db/init.sql; every statement is idempotent so upgrading a schema
# that init.sql already built is a no-op. One statement per op.execute: asyncpg
# prepares each call and rejects multiple commands in one statement.
#
# The column is added nullable, backfilled, then made NOT NULL so existing rows
# get a meaningful value instead of the migration time.
#
# Backfill: blobs.created_at is when the blob was stored. If another gallery
# stored the blob earlier it reads too early, so it is only a lower bound of the
# real update time; GREATEST with added_at keeps it from going before the
# gallery existed. images.added_at is NOT used: it is the file mtime, i.e. the
# original post date, not when the page reached this library. Galleries with no
# active image fall back to added_at (or now()).
#
# The trigger keeps the value current afterwards: any UPDATE that raises pages
# bumps it; unchanged or lower pages never do. The function body must stay
# textually identical to db/init.sql (a contract test compares them).


def upgrade() -> None:
    op.execute("ALTER TABLE galleries ADD COLUMN IF NOT EXISTS content_updated_at TIMESTAMPTZ")
    op.execute(
        """
        UPDATE galleries g SET content_updated_at = GREATEST(g.added_at, x.last_blob)
        FROM (
            SELECT i.gallery_id, max(b.created_at) AS last_blob
            FROM images i JOIN blobs b ON b.sha256 = i.blob_sha256
            WHERE i.visibility = 'active'
            GROUP BY i.gallery_id
        ) x
        WHERE x.gallery_id = g.id AND g.content_updated_at IS NULL
        """
    )
    op.execute("UPDATE galleries SET content_updated_at = COALESCE(added_at, now()) WHERE content_updated_at IS NULL")
    op.execute("ALTER TABLE galleries ALTER COLUMN content_updated_at SET DEFAULT now()")
    op.execute("ALTER TABLE galleries ALTER COLUMN content_updated_at SET NOT NULL")
    op.execute(
        """
        CREATE OR REPLACE FUNCTION bump_gallery_content_updated_at()
        RETURNS trigger AS $$
        BEGIN
            IF NEW.pages IS NOT NULL AND NEW.pages > COALESCE(OLD.pages, 0) THEN
                NEW.content_updated_at := now();
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute("DROP TRIGGER IF EXISTS trg_galleries_content_updated_at ON galleries")
    op.execute(
        """
        CREATE TRIGGER trg_galleries_content_updated_at
        BEFORE UPDATE OF pages ON galleries
        FOR EACH ROW EXECUTE FUNCTION bump_gallery_content_updated_at()
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_galleries_live_content_updated_at_id "
        "ON galleries (content_updated_at DESC, id DESC) WHERE deleted_at IS NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_galleries_public_content_updated_at_id "
        "ON galleries (content_updated_at DESC, id DESC) WHERE deleted_at IS NULL AND visibility = 'public'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_galleries_owner_content_updated_at_id "
        "ON galleries (created_by_user_id, content_updated_at DESC, id DESC) "
        "WHERE deleted_at IS NULL AND created_by_user_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_galleries_owner_content_updated_at_id")
    op.execute("DROP INDEX IF EXISTS idx_galleries_public_content_updated_at_id")
    op.execute("DROP INDEX IF EXISTS idx_galleries_live_content_updated_at_id")
    op.execute("DROP TRIGGER IF EXISTS trg_galleries_content_updated_at ON galleries")
    op.execute("DROP FUNCTION IF EXISTS bump_gallery_content_updated_at()")
    op.execute("ALTER TABLE galleries DROP COLUMN IF EXISTS content_updated_at")
