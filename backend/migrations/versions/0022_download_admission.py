"""add durable FIFO download admission

Revision ID: 0022
Revises: 0021
Create Date: 2026-08-01
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SEQUENCE IF NOT EXISTS download_admission_ticket_seq")
    op.execute("ALTER TABLE download_jobs ADD COLUMN IF NOT EXISTS admission_key TEXT")
    op.execute("ALTER TABLE download_jobs ADD COLUMN IF NOT EXISTS admission_token UUID")
    op.execute("ALTER TABLE download_jobs ADD COLUMN IF NOT EXISTS admission_ticket BIGINT")
    op.execute(
        """
        WITH ranked AS (
            SELECT id, row_number() OVER (ORDER BY created_at, id) AS ticket
            FROM download_jobs
            WHERE admission_ticket IS NULL
        )
        UPDATE download_jobs AS job
        SET admission_ticket = ranked.ticket
        FROM ranked
        WHERE job.id = ranked.id
        """
    )
    op.execute(
        """
        SELECT setval(
            'download_admission_ticket_seq',
            GREATEST(COALESCE((SELECT max(admission_ticket) FROM download_jobs), 0), 1),
            EXISTS (SELECT 1 FROM download_jobs)
        )
        """
    )
    op.execute(
        "ALTER TABLE download_jobs ALTER COLUMN admission_ticket SET DEFAULT nextval('download_admission_ticket_seq')"
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_download_jobs_admission_fifo
        ON download_jobs (admission_key, admission_ticket, id)
        WHERE status = 'queued' AND admission_token IS NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_download_jobs_admission_token
        ON download_jobs (admission_token)
        WHERE admission_token IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_download_jobs_admission_token")
    op.execute("DROP INDEX IF EXISTS idx_download_jobs_admission_fifo")
    op.execute("ALTER TABLE download_jobs DROP COLUMN IF EXISTS admission_ticket")
    op.execute("ALTER TABLE download_jobs DROP COLUMN IF EXISTS admission_token")
    op.execute("ALTER TABLE download_jobs DROP COLUMN IF EXISTS admission_key")
    op.execute("DROP SEQUENCE IF EXISTS download_admission_ticket_seq")
