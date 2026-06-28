"""initial schema (consolidated baseline)

Revision ID: 0001
Revises:
Create Date: 2026-03-12

This is the consolidated baseline migration representing the full schema
as of v0.4 (formerly revisions 0001–0008 + 0002_multi_user_permissions).
The complete schema is managed by db/init.sql.

Bootstrap is automated by the compose ``migrate`` service
(``scripts/bootstrap_db.py``); no manual ``alembic stamp`` is required for a
normal ``docker compose up``. If you ever bootstrap a fresh DB by hand, apply
db/init.sql then ``alembic stamp head`` (NOT ``stamp 0001`` — init.sql already
includes the 0002/0003 schema, so stamping 0001 would make ``upgrade head``
re-run those migrations).
"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Full schema is created by db/init.sql.
    # This revision exists so Alembic has a baseline to track from.
    pass


def downgrade() -> None:
    # Cannot downgrade the baseline — use db/init.sql to recreate.
    pass
