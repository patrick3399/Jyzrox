"""allow automatic browser locale preferences

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-10
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Locale was originally defaulted to en, which made it impossible to tell
    # automatic browser choice from an explicit English preference. Existing
    # English defaults become automatic; non-English values remain overrides.
    op.execute("ALTER TABLE users ALTER COLUMN locale DROP DEFAULT")
    op.execute("UPDATE users SET locale = NULL WHERE locale = 'en'")


def downgrade() -> None:
    op.execute("UPDATE users SET locale = 'en' WHERE locale IS NULL")
    op.execute("ALTER TABLE users ALTER COLUMN locale SET DEFAULT 'en'")
