"""Focused regression tests for Pixiv author collection discovery."""

from datetime import UTC
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from worker.helpers import enqueue_download_job
from worker.pixiv_collection import _discover, _published_at


@pytest.fixture(autouse=True)
def _no_pagination_delay():
    with patch("worker.pixiv_collection.get_typed_download_delay", new_callable=AsyncMock, return_value=0) as delay:
        yield delay


class _Client:
    def __init__(self, pages: dict[int, dict]):
        self.pages = pages
        self.calls: list[int] = []

    async def user_illusts(self, user_id: int, *, type: str | None = "illust", offset: int = 0):
        assert user_id == 1960050
        assert type is None
        self.calls.append(offset)
        return self.pages[offset]


@pytest.mark.asyncio
async def test_discover_full_catalogue_is_newest_first_and_exhaustive():
    client = _Client(
        {
            0: {"illusts": [{"id": 30}, {"id": 20}], "next_offset": 2},
            2: {"illusts": [{"id": 10}], "next_offset": None},
        }
    )

    works, exhaustive = await _discover(client, 1960050, stop_at=None)

    assert [work["id"] for work in works] == [30, 20, 10]
    assert exhaustive is True
    assert client.calls == [0, 2]


@pytest.mark.asyncio
async def test_incremental_discovery_stops_at_last_known_without_redownloading_it():
    client = _Client({0: {"illusts": [{"id": 30}, {"id": 20}, {"id": 10}], "next_offset": 3}})

    works, exhaustive = await _discover(client, 1960050, stop_at="20")

    assert [work["id"] for work in works] == [30]
    assert exhaustive is False
    assert client.calls == [0]


def test_published_at_normalizes_naive_pixiv_timestamp_to_utc():
    value = _published_at({"create_date": "2026-07-13T12:34:56"})

    assert value is not None
    assert value.tzinfo == UTC


def test_published_at_rejects_invalid_timestamp():
    assert _published_at({"create_date": "not-a-date"}) is None


@pytest.mark.asyncio
async def test_collection_retry_keeps_specialized_worker_route():
    job = SimpleNamespace(
        id="job-id",
        url="https://www.pixiv.net/users/1960050",
        user_id=7,
        subscription_id=9,
        options={"pixiv_collection": True, "full_reconcile": True},
    )
    enqueue = AsyncMock()
    with patch("core.queue.enqueue", enqueue):
        await enqueue_download_job(job, "retry:job-id:1")

    enqueue.assert_awaited_once_with(
        "pixiv_collection_job",
        _job_id="retry:job-id:1",
        _timeout=86400,
        user_id=1960050,
        owner_user_id=7,
        db_job_id="job-id",
        full_reconcile=True,
        subscription_id=9,
    )


@pytest.mark.asyncio
async def test_discover_waits_the_configured_pagination_delay_between_pages(_no_pagination_delay):
    """Author catalogue paging used to burst with sleep(0); it must honour the pixiv pagination delay."""
    client = _Client(
        {
            0: {"illusts": [{"id": 30}], "next_offset": 1},
            1: {"illusts": [{"id": 20}], "next_offset": 2},
            2: {"illusts": [{"id": 10}], "next_offset": None},
        }
    )

    await _discover(client, 1960050, stop_at=None)

    assert _no_pagination_delay.await_count == 2
    _no_pagination_delay.assert_awaited_with("pixiv", "pagination", 1000)


@pytest.mark.asyncio
async def test_discover_propagates_rate_limit_instead_of_returning_a_partial_catalogue():
    from services.pixiv_client import PixivRateLimitError

    class _Throttled(_Client):
        async def user_illusts(self, user_id, *, type=None, offset=0):
            if offset:
                raise PixivRateLimitError(60)
            return {"illusts": [{"id": 30}], "next_offset": 1}

    with pytest.raises(PixivRateLimitError):
        await _discover(_Throttled({}), 1960050, stop_at=None)


async def _author_gallery(db_session, *, download_status: str, item_ids: list[str]):
    from datetime import datetime

    from db.models import Gallery, GallerySourceItem

    gallery = Gallery(
        source="pixiv",
        source_id="user:2587756",
        title="author",
        created_by_user_id=1,
        download_status=download_status,
    )
    db_session.add(gallery)
    await db_session.flush()
    # Newest first, as a newest-first sync that died part-way leaves them.
    for position, item_id in enumerate(item_ids, start=1):
        db_session.add(
            GallerySourceItem(
                gallery_id=gallery.id,
                source_item_id=f"pixiv:{item_id}",
                source_position=position,
                published_at=datetime(2026, 10, 30 - position, tzinfo=UTC),
            )
        )
    await db_session.commit()
    return gallery


@pytest.mark.asyncio
async def test_incremental_anchor_after_partial_sync_is_none_so_older_works_are_backfilled(db_session):
    """A sync that died at 370/547 keeps only the newest works. Anchoring the
    next incremental run on the newest one stops discovery immediately, skips
    the ~175 older works forever and then marks the gallery complete."""
    from worker.pixiv_collection import _gallery_resume_anchor

    await _author_gallery(db_session, download_status="partial", item_ids=["300", "200"])

    assert await _gallery_resume_anchor(db_session, user_id=2587756, owner_user_id=1) is None


@pytest.mark.asyncio
async def test_incremental_anchor_after_complete_sync_is_the_newest_work(db_session):
    from worker.pixiv_collection import _gallery_resume_anchor

    await _author_gallery(db_session, download_status="complete", item_ids=["300", "200"])

    assert await _gallery_resume_anchor(db_session, user_id=2587756, owner_user_id=1) == "300"
