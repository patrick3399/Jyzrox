"""add source and tags count indexes

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-08

Add two missing indexes for 1M-scale performance:
  - idx_galleries_source_only: single-column index on galleries.source for
    WHERE source = '<provider>' filters (distinct from the composite
    idx_galleries_source which covers (source, source_id)).
  - idx_tags_count: descending index on tags.count for ORDER BY count DESC
    queries used by the tag listing endpoint.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_galleries_source_only ON galleries (source);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tags_count ON tags (count DESC);"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_galleries_source_only;")
    op.execute("DROP INDEX IF EXISTS idx_tags_count;")
