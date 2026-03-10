"""Replace followed_artists table with subscriptions.

Revision ID: 0008
Revises: 0007
Create Date: 2026-03-10
"""
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS followed_artists")
    op.execute("""
        CREATE TABLE subscriptions (
            id              BIGSERIAL PRIMARY KEY,
            user_id         BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name            TEXT,
            url             TEXT NOT NULL,
            source          TEXT,
            source_id       TEXT,
            avatar_url      TEXT,
            enabled         BOOLEAN DEFAULT TRUE,
            auto_download   BOOLEAN DEFAULT TRUE,
            cron_expr       TEXT DEFAULT '0 */2 * * *',
            last_checked_at TIMESTAMPTZ,
            last_item_id    TEXT,
            last_status     TEXT DEFAULT 'pending',
            last_error      TEXT,
            next_check_at   TIMESTAMPTZ DEFAULT now(),
            created_at      TIMESTAMPTZ DEFAULT now(),
            UNIQUE(user_id, url)
        )
    """)
    op.execute("CREATE INDEX idx_subscriptions_next_check ON subscriptions(next_check_at) WHERE enabled = true")
    op.execute("CREATE INDEX idx_subscriptions_user ON subscriptions(user_id)")
    op.execute("CREATE INDEX idx_subscriptions_source ON subscriptions(source, source_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS subscriptions")
    op.execute("""
        CREATE TABLE followed_artists (
            id              BIGSERIAL PRIMARY KEY,
            user_id         BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            source          TEXT NOT NULL,
            artist_id       TEXT NOT NULL,
            artist_name     TEXT,
            artist_avatar   TEXT,
            last_checked_at TIMESTAMPTZ,
            last_illust_id  TEXT,
            auto_download   BOOLEAN DEFAULT FALSE,
            added_at        TIMESTAMPTZ DEFAULT now(),
            UNIQUE (user_id, source, artist_id)
        )
    """)
