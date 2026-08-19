"""backfill gallery_tags for galleries that only have tags_array

Revision ID: 0023
Revises: 0022
Create Date: 2026-08-19
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# galleries.tags_array is a denormalised view of gallery_tags, and
# rebuild_gallery_tags_array() regenerates it from those rows. The progressive
# import path wrote only the array, so any later rebuild -- a manual tag edit, an
# alias or implication apply, a bulk edit -- replaced real source metadata with
# an almost-empty array (HR-008). The writer is fixed; this repairs the rows it
# never wrote. Measured before this migration: 89 galleries holding 1,368 tags
# backed by no junction rows at all.
#
# Two statements rather than one CTE: a data-modifying CTE's inserts are not
# visible to the rest of the same statement, so the tags rows must land before
# the join that resolves their ids.

_DIVERGED = """
    SELECT g.id AS gallery_id, u.tag_str
    FROM galleries g
    CROSS JOIN LATERAL unnest(g.tags_array) AS u(tag_str)
    WHERE cardinality(g.tags_array) > 0
      AND NOT EXISTS (SELECT 1 FROM gallery_tags gt WHERE gt.gallery_id = g.id)
"""

# Namespace splitting must match
# services/tag_helpers.upsert_metadata_gallery_tags: split on the FIRST colon,
# default namespace 'general' when there is none.
_PARSED = f"""
    SELECT gallery_id,
           CASE WHEN position(':' in tag_str) > 0
                THEN split_part(tag_str, ':', 1)
                ELSE 'general' END AS namespace,
           CASE WHEN position(':' in tag_str) > 0
                THEN substring(tag_str from position(':' in tag_str) + 1)
                ELSE tag_str END AS name
    FROM ({_DIVERGED}) AS d
"""


def upgrade() -> None:
    # 1. Materialise any tag the arrays reference but the tags table lacks.
    #    count stays 0; it is a derived statistic with its own rebuild path
    #    (services/tag_helpers.rebuild_tag_counts).
    op.execute(
        f"""
        INSERT INTO tags (namespace, name, count)
        SELECT DISTINCT namespace, name, 0
        FROM ({_PARSED}) AS p
        ON CONFLICT (namespace, name) DO NOTHING
        """
    )

    # 2. Write the junction rows the importer should have written.
    op.execute(
        f"""
        INSERT INTO gallery_tags (gallery_id, tag_id, confidence, source)
        SELECT p.gallery_id, t.id, 1.0, 'metadata'
        FROM ({_PARSED}) AS p
        JOIN tags t ON t.namespace = p.namespace AND t.name = p.name
        ON CONFLICT (gallery_id, tag_id) DO NOTHING
        """
    )


def downgrade() -> None:
    # Backfilled rows are indistinguishable from rows the importer wrote, and
    # deleting metadata-sourced gallery_tags would re-create the data loss this
    # migration repairs. Intentionally irreversible.
    pass
