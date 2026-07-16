"""add canonical download job identity

Revision ID: 0017
Revises: 0016
Create Date: 2026-07-16
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE download_jobs ADD COLUMN IF NOT EXISTS canonical_url TEXT")
    op.execute(
        """
        UPDATE download_jobs
        SET canonical_url = regexp_replace(split_part(btrim(url), '#', 1), '/+$', '')
        WHERE canonical_url IS NULL
        """
    )
    op.execute(
        """
        WITH ranked AS (
            SELECT id,
                   row_number() OVER (
                       PARTITION BY user_id, canonical_url
                       ORDER BY created_at, id
                   ) AS duplicate_rank
            FROM download_jobs
            WHERE user_id IS NOT NULL
              AND canonical_url IS NOT NULL
              AND status IN ('queued', 'running', 'paused')
        )
        UPDATE download_jobs AS job
        SET status = 'failed',
            error = COALESCE(job.error, 'Superseded duplicate active job during canonical URL migration'),
            finished_at = COALESCE(job.finished_at, now())
        FROM ranked
        WHERE job.id = ranked.id
          AND ranked.duplicate_rank > 1
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_download_jobs_active_canonical
        ON download_jobs (user_id, canonical_url)
        WHERE user_id IS NOT NULL
          AND canonical_url IS NOT NULL
          AND status IN ('queued', 'running', 'paused')
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_download_jobs_active_canonical")
    op.execute("ALTER TABLE download_jobs DROP COLUMN IF EXISTS canonical_url")
