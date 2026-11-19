"""GET /api/subscriptions/by-gallery/{id}: which subscription covers a gallery, for the gallery page."""

from unittest.mock import AsyncMock, patch

import pytest

from core.utils import normalize_download_url
from tests._download_stop_support import add_gallery, add_job, add_subscription, utc

WEIBO_URL = "https://weibo.com/u/3802725779"


def _weibo_key(url):
    return ("weibo", "3802725779") if "3802725779" in url else None


@pytest.fixture(autouse=True)
def _no_check_locks():
    with patch("routers.subscriptions._checking_flags", new=AsyncMock(side_effect=lambda ids: [False] * len(ids))):
        yield


async def _weibo_gallery(db_session, **overrides):
    return await add_gallery(
        db_session,
        source="weibo",
        source_id="3802725779",
        source_url=WEIBO_URL,
        download_status="complete",
        **overrides,
    )


async def test_by_gallery_returns_the_owning_subscription_from_its_job(client, db_session):
    gallery = await add_gallery(db_session)
    sub = await add_subscription(db_session)
    await add_job(
        db_session,
        url=normalize_download_url(sub.url),
        status="done",
        gallery_id=gallery.id,
        subscription_id=sub.id,
        created_at=utc(2026, 10, 1),
    )

    resp = await client.get(f"/api/subscriptions/by-gallery/{gallery.id}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["subscription"]["id"] == sub.id
    assert body["subscription"]["checking"] is False
    assert (body["can_subscribe"], body["subscribe_url"]) == (False, None)


async def test_by_gallery_resolves_plain_download_account_gallery_by_identity(client, db_session):
    gallery = await _weibo_gallery(db_session)
    sub = await add_subscription(
        db_session, url="https://weibo.cn/u/3802725779", source="weibo"
    )  # legacy: no source_id

    with patch("services.download_mode.account_gallery_key", side_effect=_weibo_key):
        resp = await client.get(f"/api/subscriptions/by-gallery/{gallery.id}")

    assert resp.json()["subscription"]["id"] == sub.id
    assert resp.json()["can_subscribe"] is False


async def test_by_gallery_offers_subscribe_for_unsubscribed_account_gallery(client, db_session):
    gallery = await _weibo_gallery(db_session)
    # Another user's subscription to the same account is not this user's.
    await add_subscription(
        db_session, user_id=2, url="https://weibo.cn/u/3802725779", source="weibo", source_id="3802725779"
    )

    with patch("services.download_mode.account_gallery_key", side_effect=_weibo_key):
        resp = await client.get(f"/api/subscriptions/by-gallery/{gallery.id}")

    assert resp.json() == {"subscription": None, "can_subscribe": True, "subscribe_url": WEIBO_URL}


async def test_by_gallery_does_not_offer_subscribe_for_a_non_account_gallery(client, db_session):
    gallery = await add_gallery(db_session)  # an E-Hentai gallery URL is not an account

    with patch("services.download_mode.account_gallery_key", return_value=None):
        resp = await client.get(f"/api/subscriptions/by-gallery/{gallery.id}")

    assert resp.json() == {"subscription": None, "can_subscribe": False, "subscribe_url": None}


async def test_by_gallery_trashed_gallery_returns_404(client, db_session):
    gallery = await _weibo_gallery(db_session, deleted_at=utc(2026, 11, 1))

    resp = await client.get(f"/api/subscriptions/by-gallery/{gallery.id}")

    assert resp.status_code == 404


async def test_by_gallery_invisible_gallery_returns_404_for_a_member(make_client, db_session):
    gallery = await add_gallery(db_session, created_by_user_id=1, visibility="private")

    async with make_client(user_id=2, role="member") as ac:
        resp = await ac.get(f"/api/subscriptions/by-gallery/{gallery.id}")

    assert resp.status_code == 404


async def test_by_gallery_requires_member_role(make_client, db_session):
    gallery = await add_gallery(db_session)

    async with make_client(user_id=1, role="viewer") as ac:
        resp = await ac.get(f"/api/subscriptions/by-gallery/{gallery.id}")

    assert resp.status_code == 403
