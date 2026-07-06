"""Tests for core.schema_guard — the startup schema-version fail-fast.

api and worker call ``assert_db_at_head`` at boot so a DB that was not migrated
up to the app image's alembic head (e.g. a migrate image older than the app
image in a distributed/pull deployment) refuses to start instead of serving on
a stale schema.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core import schema_guard


class TestVerifyAtHead:
    def test_passes_when_db_at_single_head(self):
        schema_guard.verify_at_head("0004", ("0004",))  # must not raise

    def test_raises_when_db_behind_head(self):
        with pytest.raises(RuntimeError, match="0003.*0004|not at head|head"):
            schema_guard.verify_at_head("0003", ("0004",))

    def test_raises_when_multiple_heads(self):
        with pytest.raises(RuntimeError, match="[Mm]ultiple|head"):
            schema_guard.verify_at_head("0004", ("0004", "0004xyz"))

    def test_raises_when_no_revision_recorded(self):
        with pytest.raises(RuntimeError):
            schema_guard.verify_at_head(None, ("0004",))


class TestAssertDbAtHead:
    @pytest.mark.asyncio
    async def test_passes_when_revision_matches_head(self):
        with (
            patch.object(schema_guard, "alembic_heads", MagicMock(return_value=("0004",))),
            patch.object(schema_guard, "current_db_revision", AsyncMock(return_value="0004")),
        ):
            await schema_guard.assert_db_at_head("postgresql://x/y")  # must not raise

    @pytest.mark.asyncio
    async def test_raises_when_db_behind_app_head(self):
        # Stale migrate image applied 0003 but this app image's head is 0004.
        with (
            patch.object(schema_guard, "alembic_heads", MagicMock(return_value=("0004",))),
            patch.object(schema_guard, "current_db_revision", AsyncMock(return_value="0003")),
        ):
            with pytest.raises(RuntimeError):
                await schema_guard.assert_db_at_head("postgresql://x/y")
