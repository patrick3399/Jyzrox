"""Placeholder — phash moved to blobs table in CAS migration.

Revision ID: 0003
Revises: 0002
Create Date: 2026-03-09
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # phash is now on the blobs table (created by init.sql or CAS migration).
    # This migration is intentionally empty.
    pass


def downgrade() -> None:
    pass
