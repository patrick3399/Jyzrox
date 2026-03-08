"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-03-08

This is a placeholder migration. The initial schema is managed by db/init.sql.
Run `alembic stamp head` on an existing database to mark it as up-to-date,
then use `alembic revision --autogenerate -m "description"` for future changes.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Initial schema is created by db/init.sql.
    # This revision exists so Alembic has a baseline to track from.
    pass


def downgrade() -> None:
    # Cannot downgrade the initial schema — use db/init.sql to recreate.
    pass
