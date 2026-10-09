"""add gallery_categories registry

Revision ID: 0029
Revises: 0028
Create Date: 2026-10-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Self-contained on purpose: a migration must not import application code.
# tests/test_gallery_categories_service.py pins this list to
# services.gallery_categories.BUILTIN_CATEGORIES.
BUILTIN_CATEGORIES: tuple[tuple[str, str, int], ...] = (
    ("Doujinshi", "pink", 1),
    ("Manga", "orange", 2),
    ("Artist CG", "yellow", 3),
    ("Game CG", "green", 4),
    ("Western", "sky", 5),
    ("Non-H", "blue", 6),
    ("Image Set", "purple", 7),
    ("Cosplay", "red", 8),
    ("Asian Porn", "rose", 9),
    ("Misc", "gray", 10),
)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS gallery_categories (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            color TEXT NOT NULL DEFAULT 'gray',
            sort_order INTEGER NOT NULL DEFAULT 0,
            is_builtin BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_gallery_categories_name_lower ON gallery_categories (lower(name))")
    insert = sa.text(
        "INSERT INTO gallery_categories (name, color, sort_order, is_builtin) "
        "VALUES (:name, :color, :sort_order, TRUE) ON CONFLICT DO NOTHING"
    )
    for name, color, sort_order in BUILTIN_CATEGORIES:
        op.get_bind().execute(insert, {"name": name, "color": color, "sort_order": sort_order})


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS gallery_categories")
