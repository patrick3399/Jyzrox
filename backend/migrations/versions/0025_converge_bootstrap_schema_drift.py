"""converge schemas that db/init.sql and the migration chain built differently

Revision ID: 0025
Revises: 0024
Create Date: 2026-10-06
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, name PostgreSQL generated for the unnamed db/init.sql constraint, name
# migrations 0003, 0009 and 0019 give the same constraint).
_CONSTRAINT_RENAMES = (
    ("images", "images_replaced_by_image_id_fkey", "fk_images_replaced_by_image_id"),
    ("workbench_operations", "workbench_operations_status_check", "ck_workbench_operation_status"),
    ("gallery_metadata_field_states", "gallery_metadata_field_states_origin_check", "ck_gallery_metadata_field_origin"),
    ("gallery_metadata_changes", "gallery_metadata_changes_origin_check", "ck_gallery_metadata_change_origin"),
    ("blob_relationships", "blob_relationships_decision_by_user_id_fkey", "fk_blob_relationship_decision_user"),
)

# Migration 0007 adds these as NOT NULL; db/init.sql declared them nullable.
_NOT_NULL_JSONB_COLUMNS = (
    ("download_jobs", "options"),
    ("subscriptions", "download_options"),
)


def upgrade() -> None:
    # A fresh database is built from db/init.sql and stamped at head, so no
    # migration ever runs against it, while an upgraded database never sees
    # init.sql again. Each side therefore missed what only the other declared.
    # Every statement is guarded: on a database that already has everything this
    # migration changes nothing.

    # 1. Migration 0008, verbatim. init.sql did not mirror it until 2026-10-06,
    #    so databases bootstrapped fresh in between are stamped past 0008
    #    without these objects and alembic will never run 0008 for them.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS gallery_source_items (
            id BIGSERIAL PRIMARY KEY,
            gallery_id BIGINT NOT NULL REFERENCES galleries(id) ON DELETE CASCADE,
            source_item_id TEXT NOT NULL,
            source_item_url TEXT,
            title TEXT,
            published_at TIMESTAMPTZ,
            page_count INTEGER NOT NULL DEFAULT 0,
            source_position INTEGER,
            source_seen_at TIMESTAMPTZ,
            status TEXT NOT NULL DEFAULT 'active',
            metadata_json JSONB NOT NULL DEFAULT '{}',
            CONSTRAINT uq_gallery_source_item UNIQUE (gallery_id, source_item_id),
            CONSTRAINT ck_gallery_source_item_status CHECK (status IN ('active', 'source_missing'))
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_gallery_source_items_gallery_order ON gallery_source_items (gallery_id, source_position)"
    )
    op.execute(
        "ALTER TABLE images ADD COLUMN IF NOT EXISTS source_item_row_id BIGINT REFERENCES gallery_source_items(id) ON DELETE SET NULL"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_images_source_item_row_id ON images (source_item_row_id)")
    op.execute(
        "ALTER TABLE read_progress ADD COLUMN IF NOT EXISTS last_image_id BIGINT REFERENCES images(id) ON DELETE SET NULL"
    )

    # 2. Objects only init.sql declared (commit 1f992ac); a database that has
    #    only ever been upgraded through alembic lacks them.
    op.execute("CREATE INDEX IF NOT EXISTS idx_read_progress_user ON read_progress (user_id, last_read_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_read_progress_gallery ON read_progress (gallery_id, last_read_at DESC)")
    # Fails, rolling the whole migration back, if a row holds any other role;
    # the API has only ever written these three.
    op.execute(
        """
        DO $$ BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conrelid = 'users'::regclass AND conname = 'chk_users_role'
          ) THEN
            ALTER TABLE users ADD CONSTRAINT chk_users_role
              CHECK (role IN ('admin', 'member', 'viewer'));
          END IF;
        END $$;
        """
    )

    # 3. Constraints init.sql left unnamed. Renamed only when the generated name
    #    exists and the migration name does not, so the names that downgrades
    #    and future migrations address exist on every database.
    for table, generated_name, migration_name in _CONSTRAINT_RENAMES:
        op.execute(
            f"""
            DO $$ BEGIN
              IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = '{table}'::regclass AND conname = '{generated_name}'
              ) AND NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = '{table}'::regclass AND conname = '{migration_name}'
              ) THEN
                ALTER TABLE {table} RENAME CONSTRAINT {generated_name} TO {migration_name};
              END IF;
            END $$;
            """
        )

    # 4. Nullability init.sql declared more loosely than migration 0007. The
    #    pg_attribute guard skips the backfill and the table lock where the
    #    column is already NOT NULL.
    for table, column in _NOT_NULL_JSONB_COLUMNS:
        op.execute(
            f"""
            DO $$ BEGIN
              IF EXISTS (
                SELECT 1 FROM pg_attribute
                WHERE attrelid = '{table}'::regclass AND attname = '{column}' AND NOT attnotnull
              ) THEN
                UPDATE {table} SET {column} = '{{}}' WHERE {column} IS NULL;
                ALTER TABLE {table} ALTER COLUMN {column} SET NOT NULL;
              END IF;
            END $$;
            """
        )


def downgrade() -> None:
    # Nothing here is new at this revision: every object belongs to the schema
    # that 0008 or init.sql already defines at 0024, and whether this migration
    # created it or found it in place is not recorded. Intentionally a no-op.
    pass
