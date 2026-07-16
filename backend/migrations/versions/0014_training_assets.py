"""add LoRA and generated image assets

Revision ID: 0014
Revises: 0013
Create Date: 2026-07-16
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS lora_models (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            dataset_id BIGINT REFERENCES datasets(id) ON DELETE SET NULL,
            name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            file_size BIGINT NOT NULL,
            sha256 TEXT NOT NULL,
            trigger_words JSONB NOT NULL DEFAULT '[]'::jsonb,
            training_params JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_lora_models_user_created ON lora_models (user_id, created_at DESC)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS generated_image_metadata (
            image_id BIGINT PRIMARY KEY REFERENCES images(id) ON DELETE CASCADE,
            prompt_json JSONB,
            workflow_json JSONB,
            imported_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS generated_image_metadata")
    op.execute("DROP TABLE IF EXISTS lora_models")
