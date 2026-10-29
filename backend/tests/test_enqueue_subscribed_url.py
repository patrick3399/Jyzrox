"""POST /api/download/ for a URL the user subscribes to needs an explicit confirmation."""

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import func, select

from db.models import DownloadJob
from tests._download_stop_support import EH_URL, add_subscription


@pytest.fixture
def enq():
    mock = AsyncMock()
    with (
        patch("core.queue.enqueue", mock),
        patch("routers.download._check_source_enabled", new_callable=AsyncMock),
        patch("services.credential.get_credential", new_callable=AsyncMock, return_value=None),
    ):
        yield mock


async def _job_count(db_session) -> int:
    return (await db_session.execute(select(func.count()).select_from(DownloadJob))).scalar_one()


async def test_enqueue_subscribed_url_requires_confirmation(client, db_session, enq):
    sub = await add_subscription(db_session, user_id=1, url=EH_URL, name="My artist")

    resp = await client.post("/api/download/", json={"url": EH_URL})

    assert resp.status_code == 409
    assert resp.json()["detail"] == {"code": "subscribed", "subscription_id": sub.id, "name": "My artist"}
    assert await _job_count(db_session) == 0
    enq.assert_not_awaited()


async def test_enqueue_subscribed_url_matches_after_url_normalization(client, db_session, enq):
    """The comparison is on the canonical URL, so a trailing-slash variant of the subscription URL still matches."""
    sub = await add_subscription(db_session, user_id=1, url=EH_URL)

    resp = await client.post("/api/download/", json={"url": EH_URL.rstrip("/")})

    assert resp.status_code == 409
    assert resp.json()["detail"]["subscription_id"] == sub.id


async def test_enqueue_subscribed_url_with_confirmation_enqueues(client, db_session, enq):
    await add_subscription(db_session, user_id=1, url=EH_URL)

    resp = await client.post("/api/download/", json={"url": EH_URL, "confirm_subscribed": True})

    assert resp.status_code == 200
    job = (await db_session.execute(select(DownloadJob))).scalar_one()
    assert resp.json()["job_id"] == str(job.id)
    assert job.mode == "download"  # a confirmed manual run is not a subscription run
    assert job.subscription_id is None
    enq.assert_awaited_once()


async def test_enqueue_url_subscribed_by_another_user_is_not_blocked(client, db_session, enq):
    await add_subscription(db_session, user_id=2, url=EH_URL)

    resp = await client.post("/api/download/", json={"url": EH_URL})

    assert resp.status_code == 200
    assert await _job_count(db_session) == 1


async def test_enqueue_url_without_subscription_is_unaffected(client, db_session, enq):
    await add_subscription(db_session, user_id=1, url="https://x.com/someone")

    resp = await client.post("/api/download/", json={"url": EH_URL})

    assert resp.status_code == 200
