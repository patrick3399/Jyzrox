"""A Pixiv author-collection repair traverses the whole catalogue and never moves the subscription boundary."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests._download_stop_support import add_gallery, add_job, add_subscription

PIXIV_URL = "https://www.pixiv.net/users/999"


@pytest.mark.parametrize(
    "mode,options,expected",
    [
        ("repair", {"pixiv_collection": True}, True),
        ("download", {"pixiv_collection": True, "force_full_scan": True}, True),  # legacy repair row
        ("subscription_incremental", {"pixiv_collection": True}, False),
        ("subscription_initial", {"pixiv_collection": True}, False),
    ],
)
async def test_pixiv_repair_dispatches_full_reconcile(mode, options, expected):
    """An incremental run stops at the subscription's last item and would repair nothing."""
    from worker.helpers import enqueue_download_job

    job = SimpleNamespace(
        id="0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d",
        url=PIXIV_URL,
        options=options,
        mode=mode,
        user_id=1,
        subscription_id=4,
        status="queued",
    )
    enqueue = AsyncMock()
    with patch("core.queue.enqueue", enqueue):
        await enqueue_download_job(job, "key")

    assert enqueue.await_args.args == ("pixiv_collection_job",)
    assert enqueue.await_args.kwargs["full_reconcile"] is expected


class _SkipPgInsert:
    """Session proxy: the PG-only upsert of source items cannot run on SQLite; everything else is real."""

    def __init__(self, session):
        self._session = session

    async def execute(self, stmt, *args, **kwargs):
        if getattr(stmt, "is_insert", False):
            return MagicMock()
        return await self._session.execute(stmt, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._session, name)


async def _run_collection(db_session, db_session_factory, *, mode, full_reconcile):
    from worker.pixiv_collection import pixiv_collection_job

    gallery = await add_gallery(db_session, source="pixiv", source_id="user:999")
    sub = await add_subscription(db_session, url=PIXIV_URL, last_item_id="old-item", last_status="pending")
    job = await add_job(
        db_session,
        url=PIXIV_URL,
        source="pixiv",
        status="running",
        mode=mode,
        options={"pixiv_collection": True},
        subscription_id=sub.id,
    )

    importer = MagicMock()
    importer.skipped_trashed = False
    importer.gallery_id = gallery.id
    importer.ensure_gallery_from_import_data = AsyncMock()
    importer.finalize = AsyncMock()

    class _Client:
        def __init__(self, _token):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        async def user_detail(self, _user_id):
            return {"name": "Some Artist"}

    @asynccontextmanager
    async def _session():
        async with db_session_factory() as session:
            yield _SkipPgInsert(session)

    redis = SimpleNamespace(set=AsyncMock(return_value=True), get=AsyncMock(return_value=None), delete=AsyncMock())
    works = [{"id": 123, "title": "w", "page_count": 1}]
    with (
        patch("worker.pixiv_collection.get_credential", AsyncMock(return_value="token")),
        patch("worker.pixiv_collection._set_job_status", AsyncMock()),
        patch("worker.pixiv_collection._set_job_progress", AsyncMock()),
        patch("worker.pixiv_collection.emit_safe", AsyncMock()),
        patch("worker.pixiv_collection.PixivClient", _Client),
        patch("worker.pixiv_collection.AsyncSessionLocal", _session),
        patch("worker.pixiv_collection._discover", AsyncMock(return_value=(works, True))),
        patch("worker.pixiv_collection._published_at", return_value=datetime(2026, 10, 1, tzinfo=UTC)),
        patch("worker.pixiv_collection._work_metadata", return_value={}),
        patch("worker.pixiv_collection.download_pixiv_illust", AsyncMock(return_value={"status": "done"})),
        patch("worker.pixiv_collection.get_typed_download_delay", AsyncMock(return_value=0)),
        patch("worker.pixiv_collection._reorder_author_gallery", AsyncMock()),
        patch("worker.pixiv_collection.ProgressiveImporter", MagicMock(return_value=importer)),
    ):
        result = await pixiv_collection_job(
            {"redis": redis},
            user_id=999,
            owner_user_id=1,
            db_job_id=str(job.id),
            full_reconcile=full_reconcile,
            subscription_id=sub.id,
        )
    db_session.expire_all()
    await db_session.refresh(sub)
    return result, sub


async def test_pixiv_repair_does_not_move_subscription_boundary(db_session, db_session_factory):
    result, sub = await _run_collection(db_session, db_session_factory, mode="repair", full_reconcile=True)

    assert result["status"] == "done"
    assert sub.last_success_at is None  # a repair re-fetches what the subscription covers; it owns no boundary
    assert sub.last_item_id == "old-item"
    assert sub.last_status == "done"  # the outcome is still reported


async def test_pixiv_incremental_run_still_moves_subscription_boundary(db_session, db_session_factory):
    """Control for the repair test above: the same harness moves the boundary for a normal run."""
    result, sub = await _run_collection(
        db_session, db_session_factory, mode="subscription_incremental", full_reconcile=False
    )

    assert result["status"] == "done"
    assert sub.last_success_at is not None
    assert sub.last_item_id == "123"
