"""add collections tables

Revision ID: 0005
Revises: 0004
Create Date: 2026-03-10
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE collections (
            id BIGSERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            cover_gallery_id BIGINT REFERENCES galleries(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now()
        );

        CREATE TABLE collection_galleries (
            collection_id BIGINT REFERENCES collections(id) ON DELETE CASCADE,
            gallery_id BIGINT REFERENCES galleries(id) ON DELETE CASCADE,
            position INTEGER DEFAULT 0,
            added_at TIMESTAMPTZ DEFAULT now(),
            PRIMARY KEY (collection_id, gallery_id)
        );

        CREATE INDEX idx_collection_galleries_gallery ON collection_galleries(gallery_id);
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE IF EXISTS collection_galleries;
        DROP TABLE IF EXISTS collections;
    """)
