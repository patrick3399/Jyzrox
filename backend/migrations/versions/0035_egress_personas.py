"""egress personas for gallery-dl downloads (ADR 0022)

Revision ID: 0035
Revises: 0034
Create Date: 2026-10-24
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0035"
down_revision: str | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Same DDL as db/init.sql; every statement is idempotent so upgrading a schema
# that init.sql already built is a no-op. One statement per op.execute: asyncpg
# prepares each call and rejects multiple commands in one statement.
_UPGRADE = (
    """
    CREATE TABLE IF NOT EXISTS egress_personas (
        id              BIGSERIAL PRIMARY KEY,
        name            TEXT NOT NULL UNIQUE,
        proxy_url       TEXT,
        user_agent      TEXT,
        browser_profile TEXT CHECK (browser_profile IN ('chrome', 'firefox')),
        enabled         BOOLEAN NOT NULL DEFAULT TRUE,
        last_exit_ip    TEXT,
        last_tested_at  TIMESTAMPTZ,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT ck_egress_personas_one_identity CHECK (browser_profile IS NULL OR user_agent IS NULL)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS persona_accounts (
        persona_id BIGINT NOT NULL REFERENCES egress_personas(id) ON DELETE CASCADE,
        source     TEXT NOT NULL,
        account    TEXT NOT NULL,
        PRIMARY KEY (persona_id, source),
        CONSTRAINT uq_persona_accounts_account UNIQUE (source, account),
        CONSTRAINT fk_persona_accounts_credential FOREIGN KEY (source, account)
            REFERENCES credentials(source, account) ON DELETE CASCADE
    )
    """,
    "ALTER TABLE download_jobs ADD COLUMN IF NOT EXISTS persona_id BIGINT",
    "ALTER TABLE download_jobs ADD COLUMN IF NOT EXISTS persona_name TEXT",
    """
    DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_download_jobs_persona') THEN
            ALTER TABLE download_jobs ADD CONSTRAINT fk_download_jobs_persona
                FOREIGN KEY (persona_id) REFERENCES egress_personas(id) ON DELETE SET NULL;
        END IF;
    END $$
    """,
)


def upgrade() -> None:
    for statement in _UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    op.execute("ALTER TABLE download_jobs DROP CONSTRAINT IF EXISTS fk_download_jobs_persona")
    op.execute("ALTER TABLE download_jobs DROP COLUMN IF EXISTS persona_name")
    op.execute("ALTER TABLE download_jobs DROP COLUMN IF EXISTS persona_id")
    op.execute("DROP TABLE IF EXISTS persona_accounts")
    op.execute("DROP TABLE IF EXISTS egress_personas")
