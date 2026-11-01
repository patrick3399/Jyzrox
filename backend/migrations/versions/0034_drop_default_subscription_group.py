"""drop the seeded Default subscription group

Revision ID: 0034
Revises: 0033
Create Date: 2026-10-23
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0034"
down_revision: str | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# init.sql seeded a system group named 'Default', but nothing ever assigns
# subscriptions to it: new subscriptions are ungrouped (group_id NULL) and the
# UI shows them as "Uncategorized". The seed is gone from init.sql; this removes
# the row from existing databases. A Default that still holds subscriptions is
# left alone -- deleting it would move them from the group schedule to their
# own cron with a stale next_check_at.


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM subscription_groups
        WHERE is_system = true
          AND name = 'Default'
          AND NOT EXISTS (
              SELECT 1 FROM subscriptions s WHERE s.group_id = subscription_groups.id
          )
        """
    )


def downgrade() -> None:
    # The group was never used; not worth recreating.
    pass
