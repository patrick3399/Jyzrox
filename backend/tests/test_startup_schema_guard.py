"""api and worker must refuse to start when the DB is not at the app's schema head.

This is the distributed-deploy backstop: if a stale/mismatched migrate step
leaves the DB behind the app image's alembic head, the app process must fail
fast (crash-loop) rather than serve on a stale schema. The guard is placed
first in each startup path, so patching it to raise aborts before any Redis /
plugin init runs.
"""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_api_startup_aborts_when_db_not_at_head():
    # conftest replaces main.lifespan with a noop for the session, so test the
    # named seam the real lifespan calls first.
    from main import _verify_schema_current

    with patch("core.schema_guard.assert_db_at_head", AsyncMock(side_effect=RuntimeError("stale schema"))):
        with pytest.raises(RuntimeError, match="stale schema"):
            await _verify_schema_current()


@pytest.mark.asyncio
async def test_worker_startup_aborts_when_db_not_at_head():
    import worker

    with patch("core.schema_guard.assert_db_at_head", AsyncMock(side_effect=RuntimeError("stale schema"))):
        with pytest.raises(RuntimeError, match="stale schema"):
            await worker.startup({})
