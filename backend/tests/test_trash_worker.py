"""Tests for worker/trash.py.

Covers:
- trash_gc_job: uses configured retention_days from settings_store
- trash_gc_job: defaults to 30 days when no setting exists
- trash_gc_job: returns deleted=0 when no galleries are expired
- trash_gc_job: calls hard_delete_in_chunks for expired galleries
- hard_delete_in_chunks: a failing chunk is counted, not raised
"""

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure backend is on the path
_backend_dir = os.path.join(os.path.dirname(__file__), "..")
if os.path.abspath(_backend_dir) not in sys.path:
    sys.path.insert(0, os.path.abspath(_backend_dir))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_session(galleries: list | None = None):
    """Return a mock async context-manager session."""
    if galleries is None:
        galleries = []

    session = AsyncMock()
    session.commit = AsyncMock()

    scalars_mock = MagicMock()
    scalars_mock.all.return_value = galleries
    scalars_mock.__iter__.side_effect = lambda: iter(galleries)
    execute_result = MagicMock()
    execute_result.scalars.return_value = scalars_mock
    session.execute = AsyncMock(return_value=execute_result)

    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


def _make_gallery(gallery_id: int = 1):
    """Return a MagicMock representing a Gallery row."""
    g = MagicMock()
    g.id = gallery_id
    g.title = f"Gallery {gallery_id}"
    return g


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestTrashGcJob:
    """Unit tests for trash_gc_job()."""

    async def test_no_retention_setting_defaults_to_30_days(self):
        """When no retention setting exists, get_int_setting returns the default of 30."""
        from worker.trash import trash_gc_job

        session = _make_mock_session(galleries=[])

        with (
            patch("worker.trash.get_int_setting", new_callable=AsyncMock, return_value=30) as mock_get_int,
            patch("worker.trash.AsyncSessionLocal", return_value=session),
            patch("worker.trash.get_toggle", new_callable=AsyncMock, return_value=True),
            patch("core.events.emit_safe", new_callable=AsyncMock),
        ):
            result = await trash_gc_job({})

        assert result["status"] == "ok"
        assert result["deleted"] == 0
        mock_get_int.assert_awaited_once_with("setting:trash_retention_days", 30)

    async def test_custom_retention_days_used_for_cutoff(self):
        """When a custom retention is configured, get_int_setting returns it."""
        from worker.trash import trash_gc_job

        session = _make_mock_session(galleries=[])

        with (
            patch("worker.trash.get_int_setting", new_callable=AsyncMock, return_value=7),
            patch("worker.trash.AsyncSessionLocal", return_value=session),
            patch("worker.trash.get_toggle", new_callable=AsyncMock, return_value=True),
            patch("core.events.emit_safe", new_callable=AsyncMock),
        ):
            result = await trash_gc_job({})

        assert result["status"] == "ok"
        assert result["deleted"] == 0

    async def test_no_galleries_to_delete_returns_zero(self):
        """When no galleries match the cutoff, returns deleted=0 without calling hard_delete."""
        from worker.trash import trash_gc_job

        session = _make_mock_session(galleries=[])

        with (
            patch("worker.trash.get_int_setting", new_callable=AsyncMock, return_value=30),
            patch("worker.trash.AsyncSessionLocal", return_value=session),
            patch("worker.trash.get_toggle", new_callable=AsyncMock, return_value=True),
            patch("core.events.emit_safe", new_callable=AsyncMock),
            patch(
                "worker.trash.hard_delete_in_chunks",
                new_callable=AsyncMock,
            ) as mock_delete,
        ):
            result = await trash_gc_job({})

        assert result["status"] == "ok"
        assert result["deleted"] == 0
        mock_delete.assert_not_awaited()

    async def test_expired_galleries_are_hard_deleted(self):
        """When expired galleries exist, hard_delete_in_chunks is called with their ids."""
        from worker.trash import trash_gc_job

        galleries = [_make_gallery(1), _make_gallery(2)]
        session = _make_mock_session(galleries=galleries)
        delete_result = {"affected": 2, "deleted": 2}

        with (
            patch("worker.trash.get_int_setting", new_callable=AsyncMock, return_value=30),
            patch("worker.trash.AsyncSessionLocal", return_value=session),
            patch("worker.trash.get_toggle", new_callable=AsyncMock, return_value=True),
            patch("core.events.emit_safe", new_callable=AsyncMock),
            patch(
                "worker.trash.hard_delete_in_chunks",
                new_callable=AsyncMock,
                return_value=delete_result,
            ) as mock_delete,
        ):
            result = await trash_gc_job({})

        mock_delete.assert_awaited_once()
        assert mock_delete.await_args.args[1] == galleries
        assert result["status"] == "ok"
        assert result["affected"] == 2

    async def test_gc_chunk_failure_is_counted_not_raised(self):
        """A chunk whose hard delete raises is logged and counted (failed_chunks), not propagated."""
        from unittest.mock import AsyncMock as AM

        from services.gallery_lifecycle import hard_delete_in_chunks

        def factory():
            s = AM()
            s.__aenter__ = AM(return_value=s)
            s.__aexit__ = AM(return_value=False)
            r = MagicMock()
            r.scalars.return_value.all.return_value = [_make_gallery(1)]
            s.execute = AM(return_value=r)
            return s

        with patch(
            "services.gallery_lifecycle.hard_delete_galleries",
            new_callable=AM,
            side_effect=RuntimeError("DB connection lost"),
        ):
            result = await hard_delete_in_chunks(factory, [1, 2, 3], chunk_size=2)

        assert result["failed_chunks"] == 2
        assert result["affected"] == 0


# ---------------------------------------------------------------------------
# Regression: edge case #93 — zero/negative retention must not delete all galleries
# ---------------------------------------------------------------------------


class TestTrashGcJobRetentionGuard:
    """retention_days <= 0 must fall back to 30, not compute cutoff=now() — edge case #93."""

    async def test_zero_retention_days_logs_warning_and_succeeds(self, caplog):
        """get_int_setting returning 0 must trigger a warning and use the 30-day default.

        Before the fix, retention_days=0 produced cutoff=datetime.now(), which
        matched every trashed gallery (deleted_at < now()) and deleted them all.
        """
        import logging

        from worker.trash import trash_gc_job

        session = _make_mock_session(galleries=[])

        with (
            patch("worker.trash.get_int_setting", new_callable=AsyncMock, return_value=0),
            patch("worker.trash.AsyncSessionLocal", return_value=session),
            patch("worker.trash.get_toggle", new_callable=AsyncMock, return_value=True),
            patch("core.events.emit_safe", new_callable=AsyncMock),
        ):
            with caplog.at_level(logging.WARNING, logger="worker.trash"):
                result = await trash_gc_job({})

        assert result["status"] == "ok"
        assert any("retention_days=0 invalid" in r.message for r in caplog.records), (
            "Expected a warning log when retention_days=0"
        )

    async def test_negative_retention_days_logs_warning_and_succeeds(self, caplog):
        """get_int_setting returning a negative value must also fall back to 30 — edge case #93."""
        import logging

        from worker.trash import trash_gc_job

        session = _make_mock_session(galleries=[])

        with (
            patch("worker.trash.get_int_setting", new_callable=AsyncMock, return_value=-5),
            patch("worker.trash.AsyncSessionLocal", return_value=session),
            patch("worker.trash.get_toggle", new_callable=AsyncMock, return_value=True),
            patch("core.events.emit_safe", new_callable=AsyncMock),
        ):
            with caplog.at_level(logging.WARNING, logger="worker.trash"):
                result = await trash_gc_job({})

        assert result["status"] == "ok"
        assert any("retention_days=-5 invalid" in r.message for r in caplog.records)


class TestTrashWorkerImportBoundary:
    """Regression: worker/trash.py must not import from any router module (STAB-004)."""

    def test_trash_worker_does_not_import_routers(self):
        import ast
        import pathlib

        source = pathlib.Path(__file__).parent.parent / "worker" / "trash.py"
        tree = ast.parse(source.read_text())

        router_imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and node.module.startswith("routers"):
                    router_imports.append(node.module)

        assert router_imports == [], f"worker/trash.py imports from routers (STAB-004 violation): {router_imports}"
