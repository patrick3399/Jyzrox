"""novel knowledge index tables (notes / links / mentions)

Derived, rebuildable index for the Phase 1 knowledge layer. Idempotent DDL so it
is safe over an init.sql-bootstrapped schema (BE-T15).

Revision ID: 0005
Revises: 0004
"""

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | None = "0004"
branch_labels = None
depends_on = None

# One statement per entry: asyncpg refuses multiple commands in a single
# prepared statement ("cannot insert multiple commands into a prepared
# statement"), so each op.execute must carry exactly one command.
_UPGRADE_STATEMENTS: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS novel_notes (
        file_path   TEXT PRIMARY KEY,
        title       TEXT NOT NULL,
        note_type   TEXT,
        aliases     TEXT[] NOT NULL DEFAULT '{}',
        frontmatter JSONB NOT NULL DEFAULT '{}',
        indexed_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS novel_links (
        src_path  TEXT NOT NULL,
        dst_title TEXT NOT NULL,
        dst_path  TEXT,
        PRIMARY KEY (src_path, dst_title)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS novel_mentions (
        note_path     TEXT NOT NULL,
        chapter_path  TEXT NOT NULL,
        mention_count INT  NOT NULL,
        first_offset  INT  NOT NULL,
        PRIMARY KEY (note_path, chapter_path)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_novel_notes_type ON novel_notes (note_type)",
    "CREATE INDEX IF NOT EXISTS idx_novel_mentions_note ON novel_mentions (note_path)",
]

_DOWNGRADE_STATEMENTS: list[str] = [
    "DROP TABLE IF EXISTS novel_mentions",
    "DROP TABLE IF EXISTS novel_links",
    "DROP TABLE IF EXISTS novel_notes",
]


def upgrade() -> None:
    for stmt in _UPGRADE_STATEMENTS:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE_STATEMENTS:
        op.execute(stmt)
