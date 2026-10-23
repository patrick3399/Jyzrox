"""ehentai galleries stop being their own artist

Revision ID: 0033
Revises: 0032
Create Date: 2026-10-23
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# E-Hentai cosplay galleries carry a ``cosplayer:`` tag but no ``artist:`` tag.
# The parsers read only ``artist:`` and the import paths then fell back to
# ``{source}:{source_id}`` -- a fallback meant for account galleries -- so each
# gallery became a one-gallery "artist" keyed by its own gid. The writers are
# fixed; this re-derives artist_id for the rows they wrote, using the same rule
# (first ``artist:`` tag, else first ``cosplayer:`` tag, else none). Measured
# before this migration: 134 of 201 ehentai galleries, 88 with a cosplayer tag.
#
# Trashed galleries and workbench-locked artist_id fields are left alone. The
# unlocked field state's source_value is rewritten too, otherwise the Inspector
# would show the old gid as a pending source change.

_DERIVED = """
    SELECT g.id,
           'ehentai:' || coalesce(
               (SELECT substr(t, 8) FROM unnest(g.tags_array) WITH ORDINALITY u(t, o)
                WHERE t LIKE 'artist:_%' ORDER BY o LIMIT 1),
               (SELECT substr(t, 11) FROM unnest(g.tags_array) WITH ORDINALITY u(t, o)
                WHERE t LIKE 'cosplayer:_%' ORDER BY o LIMIT 1)
           ) AS artist_id
    FROM galleries g
    WHERE g.source = 'ehentai'
      AND g.artist_id = 'ehentai:' || g.source_id
      AND g.deleted_at IS NULL
      AND NOT EXISTS (
          SELECT 1 FROM gallery_metadata_field_states s
          WHERE s.gallery_id = g.id AND s.field_name = 'artist_id' AND s.locked
      )
"""


def upgrade() -> None:
    op.execute(
        f"""
        WITH d AS ({_DERIVED})
        UPDATE gallery_metadata_field_states s
        SET source_value = to_jsonb(d.artist_id), updated_at = now()
        FROM d
        WHERE s.gallery_id = d.id AND s.field_name = 'artist_id' AND NOT s.locked
        """
    )
    op.execute(
        f"""
        WITH d AS ({_DERIVED})
        UPDATE galleries g
        SET artist_id = d.artist_id
        FROM d
        WHERE g.id = d.id
        """
    )


def downgrade() -> None:
    # Data repair: the bogus gid-as-artist values are not worth restoring.
    pass
