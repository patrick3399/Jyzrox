"""add gallery collaboration and review records

Revision ID: 0015
Revises: 0014
Create Date: 2026-07-16
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS gallery_permissions (
            gallery_id BIGINT NOT NULL REFERENCES galleries(id) ON DELETE CASCADE,
            user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            can_edit BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (gallery_id, user_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS gallery_share_links (
            id BIGSERIAL PRIMARY KEY,
            gallery_id BIGINT NOT NULL REFERENCES galleries(id) ON DELETE CASCADE,
            created_by_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token_hash TEXT NOT NULL UNIQUE,
            expires_at TIMESTAMPTZ,
            filter_r18 BOOLEAN NOT NULL DEFAULT true,
            revoked_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_gallery_share_links_gallery ON gallery_share_links (gallery_id)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS gallery_versions (
            gallery_id BIGINT PRIMARY KEY REFERENCES galleries(id) ON DELETE CASCADE,
            group_id TEXT NOT NULL,
            linked_by_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            linked_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_gallery_versions_group ON gallery_versions (group_id)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS import_conflicts (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            existing_gallery_id BIGINT REFERENCES galleries(id) ON DELETE SET NULL,
            source TEXT NOT NULL,
            source_id TEXT NOT NULL,
            incoming_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            status TEXT NOT NULL DEFAULT 'pending',
            resolution TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            resolved_at TIMESTAMPTZ,
            CONSTRAINT ck_import_conflict_status CHECK (status IN ('pending', 'resolved'))
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_import_conflicts_user_status ON import_conflicts (user_id, status)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS import_conflicts")
    op.execute("DROP TABLE IF EXISTS gallery_versions")
    op.execute("DROP TABLE IF EXISTS gallery_share_links")
    op.execute("DROP TABLE IF EXISTS gallery_permissions")
