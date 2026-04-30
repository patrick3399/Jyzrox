"""add image visibility and source sync state

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-29
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("images", sa.Column("visibility", sa.Text(), nullable=False, server_default="active"))
    op.add_column("images", sa.Column("source_item_id", sa.Text(), nullable=True))
    op.add_column("images", sa.Column("source_item_url", sa.Text(), nullable=True))
    op.add_column("images", sa.Column("source_position", sa.Integer(), nullable=True))
    op.add_column("images", sa.Column("source_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("images", sa.Column("hidden_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("images", sa.Column("replaced_by_image_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_images_replaced_by_image_id",
        "images",
        "images",
        ["replaced_by_image_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("idx_images_visibility", "images", ["visibility"])
    op.create_index("idx_images_source_item", "images", ["gallery_id", "source_item_id"])

    op.add_column("subscriptions", sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("subscriptions", "last_success_at")
    op.drop_index("idx_images_source_item", table_name="images")
    op.drop_index("idx_images_visibility", table_name="images")
    op.drop_constraint("fk_images_replaced_by_image_id", "images", type_="foreignkey")
    op.drop_column("images", "replaced_by_image_id")
    op.drop_column("images", "hidden_at")
    op.drop_column("images", "source_seen_at")
    op.drop_column("images", "source_position")
    op.drop_column("images", "source_item_url")
    op.drop_column("images", "source_item_id")
    op.drop_column("images", "visibility")
