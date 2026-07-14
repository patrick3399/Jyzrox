"""add library workbench metadata provenance and operations

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-14
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workbench_operations (
            id UUID PRIMARY KEY DEFAULT uuidv7(),
            user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
            kind TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            selection_count INTEGER NOT NULL DEFAULT 0,
            progress JSONB NOT NULL DEFAULT '{}',
            params JSONB NOT NULL DEFAULT '{}',
            error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            started_at TIMESTAMPTZ,
            finished_at TIMESTAMPTZ,
            CONSTRAINT ck_workbench_operation_status
                CHECK (status IN ('queued', 'running', 'completed', 'failed', 'cancelled'))
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_workbench_operations_user_id ON workbench_operations (user_id)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS gallery_metadata_field_states (
            gallery_id BIGINT NOT NULL REFERENCES galleries(id) ON DELETE CASCADE,
            field_name TEXT NOT NULL,
            origin TEXT NOT NULL DEFAULT 'source',
            locked BOOLEAN NOT NULL DEFAULT false,
            source_value JSONB,
            updated_by_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (gallery_id, field_name),
            CONSTRAINT ck_gallery_metadata_field_origin
                CHECK (origin IN ('source', 'import', 'manual', 'merge'))
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS gallery_metadata_changes (
            id BIGSERIAL PRIMARY KEY,
            gallery_id BIGINT NOT NULL REFERENCES galleries(id) ON DELETE CASCADE,
            field_name TEXT NOT NULL,
            old_value JSONB,
            new_value JSONB,
            origin TEXT NOT NULL,
            actor_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
            operation_id UUID REFERENCES workbench_operations(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_gallery_metadata_change_origin
                CHECK (origin IN ('source', 'import', 'manual', 'merge'))
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_gallery_metadata_changes_gallery_created "
        "ON gallery_metadata_changes (gallery_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_gallery_metadata_changes_operation_id "
        "ON gallery_metadata_changes (operation_id)"
    )
    op.execute(
        """
        INSERT INTO gallery_metadata_field_states
            (gallery_id, field_name, origin, locked, source_value, updated_at)
        SELECT
            galleries.id,
            fields.field_name,
            CASE WHEN galleries.source = 'local' THEN 'import' ELSE 'source' END,
            false,
            fields.field_value,
            now()
        FROM galleries
        CROSS JOIN LATERAL (
            VALUES
                ('title', to_jsonb(galleries.title)),
                ('title_jpn', to_jsonb(galleries.title_jpn)),
                ('category', to_jsonb(galleries.category)),
                ('language', to_jsonb(galleries.language)),
                ('artist_id', to_jsonb(galleries.artist_id)),
                ('uploader', to_jsonb(galleries.uploader)),
                ('visibility', to_jsonb(galleries.visibility)),
                ('pages', to_jsonb(galleries.pages)),
                ('posted_at', to_jsonb(galleries.posted_at)),
                ('rating', to_jsonb(galleries.rating))
        ) AS fields(field_name, field_value)
        ON CONFLICT (gallery_id, field_name) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS gallery_metadata_changes")
    op.execute("DROP TABLE IF EXISTS gallery_metadata_field_states")
    op.execute("DROP TABLE IF EXISTS workbench_operations")
