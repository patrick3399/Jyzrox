"""initial schema (consolidated baseline)

Revision ID: 0001
Revises:
Create Date: 2026-03-12

This is the consolidated baseline migration representing the full schema
as of v0.3 (formerly revisions 0001–0008). The complete schema is managed
by db/init.sql.

For a fresh installation:
  docker compose up -d postgres
  # db/init.sql is applied automatically via docker-entrypoint-initdb.d
  alembic stamp 0001

For an existing database already at revision 0008:
  alembic stamp 0001
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Full schema is created by db/init.sql.
    # This revision exists so Alembic has a baseline to track from.
    pass


def downgrade() -> None:
    # Cannot downgrade the baseline — use db/init.sql to recreate.
    pass
