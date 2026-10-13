"""archive rows record the job that wrote them

Revision ID: 0032
Revises: 0031
Create Date: 2026-10-14
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Every table shaped like a gallery-dl archive table, not a fixed list: the
# worker also upgrades tables gallery-dl created for an unregistered category.
_ARCHIVE_TABLES = """
    SELECT t.table_name
    FROM information_schema.tables t
    WHERE t.table_schema = 'public' AND t.table_type = 'BASE TABLE'
      AND (
          SELECT count(*) FROM information_schema.columns c
          WHERE c.table_schema = 'public' AND c.table_name = t.table_name
            AND c.column_name IN ('entry', 'gallery_id', 'job_id', 'created_at')
      ) = 4
      AND (
          SELECT count(*) FROM information_schema.columns c
          WHERE c.table_schema = 'public' AND c.table_name = t.table_name
      ) = 4
"""


def upgrade() -> None:
    # gallery-dl inserts (entry) only. Each download now connects with its job
    # id as a session setting, and this default copies it onto the row, so
    # linking no longer guesses ownership from created_at.
    op.execute(
        f"""
        DO $$
        DECLARE
            archive_table text;
        BEGIN
            FOR archive_table IN {_ARCHIVE_TABLES} LOOP
                EXECUTE format(
                    'ALTER TABLE %I ALTER COLUMN job_id '
                    'SET DEFAULT NULLIF(current_setting(''jyzrox.archive_job_id'', true), '''')::uuid',
                    archive_table
                );
            END LOOP;
        END $$
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        DO $$
        DECLARE
            archive_table text;
        BEGIN
            FOR archive_table IN {_ARCHIVE_TABLES} LOOP
                EXECUTE format('ALTER TABLE %I ALTER COLUMN job_id DROP DEFAULT', archive_table);
            END LOOP;
        END $$
        """
    )
