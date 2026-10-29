"""POST /api/download/galleries/{id}/action: repair / update from the gallery page."""

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from core.utils import normalize_download_url
from db.models import DownloadJob
from tests._download_stop_support import EH_URL, add_gallery, add_job, add_subscription, utc


@pytest.fixture
def enq():
    mock = AsyncMock()
    with (
        patch("core.queue.enqueue", mock),
        patch("routers.download._check_source_enabled", new_callable=AsyncMock),
        patch("services.credential.get_credential", new_callable=AsyncMock, return_value=None),
        # Options are passed through untouched: these tests are about inheritance, not normalization.
        patch("routers.download.normalize_download_options", new=AsyncMock(side_effect=lambda u, s, o: o)),
    ):
        yield mock


async def _jobs(db_session) -> list[DownloadJob]:
    return list((await db_session.execute(select(DownloadJob).order_by(DownloadJob.created_at))).scalars())


async def _subscribed_gallery(db_session, **sub_kwargs):
    gallery = await add_gallery(db_session)
    sub = await add_subscription(db_session, **sub_kwargs)
    await add_job(
        db_session,
        # A subscription owns the gallery as a whole only when the job fetched the subscription's own URL.
        url=normalize_download_url(sub.url),
        status="done",
        mode="subscription_incremental",
        gallery_id=gallery.id,
        subscription_id=sub.id,
        created_at=utc(2026, 10, 1),
    )
    return gallery, sub


async def test_gallery_update_on_subscription_gallery_triggers_check(client, db_session, enq):
    gallery, sub = await _subscribed_gallery(db_session)

    resp = await client.post(f"/api/download/galleries/{gallery.id}/action", json={"action": "update"})

    assert resp.status_code == 200
    assert resp.json() == {"kind": "subscription_check", "subscription_id": sub.id, "status": "queued"}
    enq.assert_awaited_once_with("check_single_subscription", _timeout=600, sub_id=sub.id)
    assert len(await _jobs(db_session)) == 1  # no download job of its own: the check creates it


async def test_gallery_update_without_subscription_enqueues_a_plain_download(client, db_session, enq):
    gallery = await add_gallery(db_session)

    resp = await client.post(f"/api/download/galleries/{gallery.id}/action", json={"action": "update"})

    assert resp.status_code == 200
    assert resp.json()["kind"] == "download"
    (job,) = await _jobs(db_session)
    # An update re-checks the source; it does not preset the gallery (repair does).
    assert (job.mode, job.gallery_id, job.subscription_id) == ("download", None, None)


async def test_gallery_repair_inherits_subscription_options(client, db_session, enq):
    options = {"media": {"max_files": 20, "include_videos": False}}
    gallery, sub = await _subscribed_gallery(db_session, download_options=options)

    resp = await client.post(f"/api/download/galleries/{gallery.id}/action", json={"action": "repair"})

    assert resp.status_code == 200
    assert resp.json()["kind"] == "repair"
    repair = (await _jobs(db_session))[-1]
    assert repair.mode == "repair"
    assert repair.subscription_id == sub.id
    assert repair.gallery_id == gallery.id
    assert repair.options == options  # without include_excluded unless asked for
    assert repair.url.startswith("https://x.com/someone")  # the subscription's URL, not the gallery's source URL


async def test_gallery_repair_include_excluded_sets_the_option(client, db_session, enq):
    gallery, _ = await _subscribed_gallery(db_session, download_options={"media": {"max_files": 5}})

    resp = await client.post(
        f"/api/download/galleries/{gallery.id}/action", json={"action": "repair", "include_excluded": True}
    )

    assert resp.status_code == 200
    repair = (await _jobs(db_session))[-1]
    assert repair.options == {"media": {"max_files": 5}, "include_excluded": True}


async def test_gallery_repair_without_subscription_uses_the_gallery_source_url(client, db_session, enq):
    gallery = await add_gallery(db_session)

    resp = await client.post(f"/api/download/galleries/{gallery.id}/action", json={"action": "repair"})

    assert resp.status_code == 200
    (job,) = await _jobs(db_session)
    assert (job.mode, job.subscription_id, job.gallery_id) == ("repair", None, gallery.id)
    assert job.url.startswith(EH_URL.rstrip("/"))


@pytest.mark.parametrize("status", ["queued", "running", "paused"])
async def test_gallery_action_rejects_active_job(client, db_session, enq, status):
    gallery = await add_gallery(db_session)
    await add_job(db_session, status=status, gallery_id=gallery.id)

    resp = await client.post(f"/api/download/galleries/{gallery.id}/action", json={"action": "repair"})

    assert resp.status_code == 409
    assert len(await _jobs(db_session)) == 1
    enq.assert_not_awaited()


async def test_gallery_action_finished_job_does_not_block(client, db_session, enq):
    gallery = await add_gallery(db_session)
    await add_job(db_session, status="done", gallery_id=gallery.id)

    resp = await client.post(f"/api/download/galleries/{gallery.id}/action", json={"action": "repair"})

    assert resp.status_code == 200


async def test_gallery_action_without_source_url_returns_422(client, db_session, enq):
    gallery = await add_gallery(db_session, source_url="")

    resp = await client.post(f"/api/download/galleries/{gallery.id}/action", json={"action": "update"})

    assert resp.status_code == 422


async def test_gallery_action_unknown_gallery_returns_404(client, enq):
    resp = await client.post("/api/download/galleries/999999/action", json={"action": "repair"})
    assert resp.status_code == 404


async def test_gallery_action_invisible_gallery_returns_404_for_a_member(make_client, db_session, enq):
    gallery = await add_gallery(db_session, created_by_user_id=1, visibility="private")

    async with make_client(user_id=2, role="member") as ac:
        resp = await ac.post(f"/api/download/galleries/{gallery.id}/action", json={"action": "repair"})

    assert resp.status_code == 404
    enq.assert_not_awaited()


async def test_gallery_action_requires_member_role(make_client, db_session, enq):
    gallery = await add_gallery(db_session)

    async with make_client(user_id=1, role="viewer") as ac:
        resp = await ac.post(f"/api/download/galleries/{gallery.id}/action", json={"action": "repair"})

    assert resp.status_code == 403
