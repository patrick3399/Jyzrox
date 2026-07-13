"""Focused regression tests for Pixiv author collection discovery."""

from datetime import UTC
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from worker.helpers import enqueue_download_job
from worker.pixiv_collection import _discover, _published_at


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
