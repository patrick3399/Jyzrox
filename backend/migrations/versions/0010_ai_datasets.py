"""add persistent AI training datasets

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-15
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS datasets (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            description TEXT,
            selection_spec JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_datasets_user_updated ON datasets (user_id, updated_at DESC)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS dataset_images (
            dataset_id BIGINT NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
            image_id BIGINT NOT NULL REFERENCES images(id) ON DELETE CASCADE,
            state TEXT NOT NULL DEFAULT 'included',
            source TEXT NOT NULL DEFAULT 'manual',
            added_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (dataset_id, image_id),
            CONSTRAINT ck_dataset_image_state CHECK (state IN ('included', 'excluded'))
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_dataset_images_image_id ON dataset_images (image_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS dataset_images")
    op.execute("DROP TABLE IF EXISTS datasets")
