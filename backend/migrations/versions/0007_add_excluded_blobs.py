"""Add excluded_blobs table for per-gallery blob exclusion.

Revision ID: 0007
Revises: 0006
Create Date: 2026-03-10
"""
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE excluded_blobs (
            gallery_id  BIGINT NOT NULL REFERENCES galleries(id) ON DELETE CASCADE,
            blob_sha256 TEXT NOT NULL,
            excluded_at TIMESTAMPTZ DEFAULT now(),
            PRIMARY KEY (gallery_id, blob_sha256)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS excluded_blobs")
