"""separate dedup evidence, decisions, and dirty revisions

Revision ID: 0019
Revises: 0018
Create Date: 2026-07-24
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE blob_relationships ALTER COLUMN relationship SET DEFAULT 'needs_context'")
    op.execute("ALTER TABLE blobs ADD COLUMN IF NOT EXISTS dedup_scanned_phash_int BIGINT")
    op.execute("ALTER TABLE blobs ADD COLUMN IF NOT EXISTS dedup_scanned_version SMALLINT")
    op.execute("ALTER TABLE blobs ADD COLUMN IF NOT EXISTS occurrence_revision BIGINT NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE blob_relationships ADD COLUMN IF NOT EXISTS context_revision_a BIGINT")
    op.execute("ALTER TABLE blob_relationships ADD COLUMN IF NOT EXISTS context_revision_b BIGINT")
    op.execute("ALTER TABLE blob_relationships ADD COLUMN IF NOT EXISTS decision TEXT")
    op.execute("ALTER TABLE blob_relationships ADD COLUMN IF NOT EXISTS decision_keep_sha TEXT")
    op.execute("ALTER TABLE blob_relationships ADD COLUMN IF NOT EXISTS decision_by_user_id BIGINT")
    op.execute("ALTER TABLE blob_relationships ADD COLUMN IF NOT EXISTS decided_at TIMESTAMPTZ")
    op.execute(
        """
        ALTER TABLE blob_relationships
        ADD CONSTRAINT fk_blob_relationship_decision_user
        FOREIGN KEY (decision_by_user_id) REFERENCES users(id) ON DELETE SET NULL
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION bump_blob_occurrence_revision()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                UPDATE blobs SET occurrence_revision = occurrence_revision + 1
                WHERE sha256 = NEW.blob_sha256;
                RETURN NEW;
            ELSIF TG_OP = 'DELETE' THEN
                UPDATE blobs SET occurrence_revision = occurrence_revision + 1
                WHERE sha256 = OLD.blob_sha256;
                RETURN OLD;
            END IF;

            IF OLD.blob_sha256 IS DISTINCT FROM NEW.blob_sha256 THEN
                UPDATE blobs SET occurrence_revision = occurrence_revision + 1
                WHERE sha256 IN (OLD.blob_sha256, NEW.blob_sha256);
            ELSIF OLD.gallery_id IS DISTINCT FROM NEW.gallery_id THEN
                UPDATE blobs SET occurrence_revision = occurrence_revision + 1
                WHERE sha256 = NEW.blob_sha256;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute("DROP TRIGGER IF EXISTS trg_images_blob_occurrence_revision ON images")
    op.execute(
        """
        CREATE TRIGGER trg_images_blob_occurrence_revision
        AFTER INSERT OR DELETE OR UPDATE OF blob_sha256, gallery_id ON images
        FOR EACH ROW EXECUTE FUNCTION bump_blob_occurrence_revision()
        """
    )
    op.execute(
        """
        UPDATE blob_relationships
        SET relationship = 'needs_review', tier = 1
        WHERE relationship = 'quality_conflict'
          AND suggested_keep IS NULL
          AND reason IS NULL
          AND diff_score IS NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_images_blob_occurrence_revision ON images")
    op.execute("DROP FUNCTION IF EXISTS bump_blob_occurrence_revision()")
    op.execute("ALTER TABLE blob_relationships DROP CONSTRAINT IF EXISTS fk_blob_relationship_decision_user")
    op.execute("ALTER TABLE blob_relationships DROP COLUMN IF EXISTS decided_at")
    op.execute("ALTER TABLE blob_relationships DROP COLUMN IF EXISTS decision_by_user_id")
    op.execute("ALTER TABLE blob_relationships DROP COLUMN IF EXISTS decision_keep_sha")
    op.execute("ALTER TABLE blob_relationships DROP COLUMN IF EXISTS decision")
    op.execute("ALTER TABLE blob_relationships DROP COLUMN IF EXISTS context_revision_b")
    op.execute("ALTER TABLE blob_relationships DROP COLUMN IF EXISTS context_revision_a")
    op.execute("ALTER TABLE blobs DROP COLUMN IF EXISTS occurrence_revision")
    op.execute("ALTER TABLE blobs DROP COLUMN IF EXISTS dedup_scanned_version")
    op.execute("ALTER TABLE blobs DROP COLUMN IF EXISTS dedup_scanned_phash_int")
    op.execute("ALTER TABLE blob_relationships ALTER COLUMN relationship SET DEFAULT 'needs_t2'")
