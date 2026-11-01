"""give every pre-created gallery-dl archive table a job_id column

Revision ID: 0028
Revises: 0027
Create Date: 2026-10-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Archive tables init.sql declared without job_id. Linking entries to a gallery
# writes job_id, so on these tables it failed and every entry stayed unlinked.
ARCHIVE_TABLES: tuple[str, ...] = (
    "instagram",
    "danbooru",
    "gelbooru",
    "newgrounds",
    "nijie",
    "kemono",
    "nhentai",
    "hitomi",
    "rule34",
)


def upgrade() -> None:
    for table in ARCHIVE_TABLES:
        op.execute(
            f"""
            DO $$
            BEGIN
                IF to_regclass('public.{table}') IS NOT NULL THEN
                    ALTER TABLE {table} ADD COLUMN IF NOT EXISTS job_id UUID;
                END IF;
            END $$
            """
        )


def downgrade() -> None:
    for table in ARCHIVE_TABLES:
        op.execute(f'ALTER TABLE IF EXISTS "{table}" DROP COLUMN IF EXISTS job_id')
