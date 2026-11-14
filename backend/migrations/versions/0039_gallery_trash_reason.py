"""galleries: record why, by whom and into what a gallery was trashed

Revision ID: 0039
Revises: 0038
Create Date: 2026-11-07
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0039"
down_revision: str | None = "0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Same DDL as db/init.sql; idempotent, one statement per op.execute.


def upgrade() -> None:
    for stmt in (
        "ALTER TABLE galleries ADD COLUMN IF NOT EXISTS deleted_reason TEXT",
        "ALTER TABLE galleries ADD COLUMN IF NOT EXISTS deleted_by_user_id BIGINT "
        "REFERENCES users(id) ON DELETE SET NULL",
        "ALTER TABLE galleries ADD COLUMN IF NOT EXISTS merged_into_gallery_id BIGINT "
        "REFERENCES galleries(id) ON DELETE SET NULL",
        "DO $$ BEGIN "
        "ALTER TABLE galleries ADD CONSTRAINT chk_galleries_deleted_reason "
        "CHECK (deleted_reason IS NULL OR deleted_reason IN ('user', 'merged', 'source_missing')); "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$",
        "UPDATE galleries SET deleted_reason = 'source_missing' "
        "WHERE deleted_at IS NOT NULL AND deleted_reason IS NULL AND download_status = 'missing'",
    ):
        op.execute(stmt)


def downgrade() -> None:
    for stmt in (
        "ALTER TABLE galleries DROP CONSTRAINT IF EXISTS chk_galleries_deleted_reason",
        "ALTER TABLE galleries DROP COLUMN IF EXISTS merged_into_gallery_id",
        "ALTER TABLE galleries DROP COLUMN IF EXISTS deleted_by_user_id",
        "ALTER TABLE galleries DROP COLUMN IF EXISTS deleted_reason",
    ):
        op.execute(stmt)
