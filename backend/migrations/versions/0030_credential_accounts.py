"""credentials: one row per (source, account), one active account per source

Revision ID: 0030
Revises: 0029
Create Date: 2026-10-10
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE credentials ADD COLUMN IF NOT EXISTS account TEXT NOT NULL DEFAULT 'default'")
    op.execute("ALTER TABLE credentials ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT FALSE")
    # Swap the single-column primary key for (source, account). Skipped when the
    # key already has two columns (a database built from the current db/init.sql).
    op.execute(
        """
        DO $$
        DECLARE
            pk_name text;
            pk_width int;
        BEGIN
            SELECT conname, array_length(conkey, 1) INTO pk_name, pk_width
            FROM pg_constraint
            WHERE conrelid = 'credentials'::regclass AND contype = 'p';
            IF pk_name IS NOT NULL AND pk_width = 1 THEN
                EXECUTE format('ALTER TABLE credentials DROP CONSTRAINT %I', pk_name);
                pk_name := NULL;
            END IF;
            IF pk_name IS NULL THEN
                ALTER TABLE credentials ADD CONSTRAINT credentials_pkey PRIMARY KEY (source, account);
            END IF;
        END $$;
        """
    )
    # A source with no active account gets its first one activated. Before this
    # revision a source had exactly one row, so that row becomes the active one.
    op.execute(
        """
        UPDATE credentials AS c
        SET is_active = TRUE
        WHERE NOT EXISTS (SELECT 1 FROM credentials AS a WHERE a.source = c.source AND a.is_active)
          AND c.account = (SELECT min(m.account) FROM credentials AS m WHERE m.source = c.source)
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_credentials_active_per_source ON credentials (source) WHERE is_active"
    )


def downgrade() -> None:
    """Destructive: a source can hold one credential again, so inactive accounts are deleted."""
    op.execute("DROP INDEX IF EXISTS uq_credentials_active_per_source")
    # Guarded so a second downgrade (is_active already dropped) is a no-op.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'credentials' AND column_name = 'is_active'
            ) THEN
                DELETE FROM credentials WHERE NOT is_active;
            END IF;
        END $$;
        """
    )
    op.execute("ALTER TABLE credentials DROP CONSTRAINT IF EXISTS credentials_pkey")
    op.execute("ALTER TABLE credentials ADD CONSTRAINT credentials_pkey PRIMARY KEY (source)")
    op.execute("ALTER TABLE credentials DROP COLUMN IF EXISTS is_active")
    op.execute("ALTER TABLE credentials DROP COLUMN IF EXISTS account")
