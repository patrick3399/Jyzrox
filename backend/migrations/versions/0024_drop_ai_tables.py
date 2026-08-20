"""drop AI subsystem tables and columns

Revision ID: 0024
Revises: 0023
Create Date: 2026-08-20
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # All three are leaf tables: nothing carries a foreign key to them, and
    # lora_models' own reference points at datasets, which survives. Verified
    # empty on 2026-08-19 (0 rows each).
    op.execute("DROP TABLE IF EXISTS image_tags")
    op.execute("DROP TABLE IF EXISTS generated_image_metadata")
    op.execute("DROP TABLE IF EXISTS lora_models")

    # images.tags_array was written only by the WD14 job and was empty on all
    # 146,675 rows, which is why /images?tags= returned nothing for every tag.
    op.execute("DROP INDEX IF EXISTS idx_images_tags_gin")
    op.execute("ALTER TABLE images DROP COLUMN IF EXISTS tags_array")

    # Its only surviving reader filtered on ImageTag confidence.
    op.execute("ALTER TABLE datasets DROP COLUMN IF EXISTS tag_threshold")

    # gallery_tags survives; only rows the AI job would have written go. This
    # must run before galleries.tags_array is rebuilt from the table, but no
    # rebuild is triggered here and the count is 0 today.
    op.execute("DELETE FROM gallery_tags WHERE source = 'ai'")


def downgrade() -> None:
    # The dropped data cannot be reconstructed and the features that wrote it
    # are gone. Intentionally irreversible.
    pass
