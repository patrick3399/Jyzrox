"""services/download_mode.py: the mode resolver and the policy that follows from it."""

import uuid

import pytest

from core.utils import normalize_download_url
from services import download_mode as dm
from tests._download_stop_support import add_gallery, add_job, add_subscription, utc

JOB_ID = "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"


def test_subscription_mode_without_boundary_is_initial():
    assert dm.subscription_mode(has_boundary=False, force_full_scan=False) == dm.SUBSCRIPTION_INITIAL


def test_subscription_mode_with_boundary_is_incremental():
    assert dm.subscription_mode(has_boundary=True, force_full_scan=False) == dm.SUBSCRIPTION_INCREMENTAL


@pytest.mark.parametrize("has_boundary", [True, False])
def test_subscription_mode_force_is_repair(has_boundary):
    """A forced re-scan wins over the boundary: repair never advances one."""
    assert dm.subscription_mode(has_boundary=has_boundary, force_full_scan=True) == dm.REPAIR


def test_effective_mode_legacy_force_full_scan_is_repair():
    """A row from before the column existed defaults to 'download'; its options say repair."""
    assert dm.effective_mode("download", {"force_full_scan": True}) == dm.REPAIR
    assert dm.effective_mode(None, {"force_full_scan": True}) == dm.REPAIR


def test_effective_mode_legacy_subscription_rows_follow_last_completed_at():
    sub = {"job_context": "subscription"}
    assert dm.effective_mode("download", sub) == dm.SUBSCRIPTION_INITIAL
    assert dm.effective_mode("download", {**sub, "last_completed_at": "2026-10-01T00:00:00"}) == (
        dm.SUBSCRIPTION_INCREMENTAL
    )


def test_effective_mode_stamped_mode_wins_over_legacy_options():
    assert dm.effective_mode(dm.SUBSCRIPTION_INITIAL, {"force_full_scan": True}) == dm.SUBSCRIPTION_INITIAL
    assert dm.effective_mode(dm.REPAIR, {}) == dm.REPAIR


def test_effective_mode_unknown_value_is_a_manual_download():
    assert dm.effective_mode("bogus", {"force_full_scan": True}) == dm.DOWNLOAD
    assert dm.effective_mode(None, None) == dm.DOWNLOAD


def test_gallery_status_on_stop_subscription_modes_are_complete_others_partial():
    assert dm.gallery_status_on_stop(dm.SUBSCRIPTION_INITIAL) == "complete"
    assert dm.gallery_status_on_stop(dm.SUBSCRIPTION_INCREMENTAL) == "complete"
    assert dm.gallery_status_on_stop(dm.DOWNLOAD) == "partial"
    assert dm.gallery_status_on_stop(dm.REPAIR) == "partial"


def test_stop_discards_is_false_only_for_repair():
    assert dm.stop_discards(dm.REPAIR) is False
    assert all(dm.stop_discards(m) for m in (dm.DOWNLOAD, dm.SUBSCRIPTION_INITIAL, dm.SUBSCRIPTION_INCREMENTAL))


def test_repair_archive_table_name_fits_postgres_limit():
    short = dm.repair_archive_table("exhentai", JOB_ID)
    assert short == f"exhentai__repair_{uuid.UUID(JOB_ID).hex}"

    long_name = dm.repair_archive_table("c" * 120, JOB_ID)
    assert len(long_name.encode()) <= 63
    # Only the category part is cut: the marker and the full job hex keep it unique and parseable.
    assert long_name.endswith(f"__repair_{uuid.UUID(JOB_ID).hex}")


def test_repair_archive_table_name_never_splits_a_multibyte_character():
    name = dm.repair_archive_table("é" * 60, JOB_ID)
    assert len(name.encode()) <= 63
    name.encode()  # would raise on a half character


async def test_find_subscription_for_url_matches_normalized_url_and_owner(db_session):
    mine = await add_subscription(db_session, user_id=1, url="https://e-hentai.org/g/1/aaaaaaaaaa/")
    await add_subscription(db_session, user_id=2, url="https://e-hentai.org/g/2/bbbbbbbbbb/")
    from core.utils import normalize_download_url

    assert (await dm.find_subscription_for_url(db_session, normalize_download_url(mine.url), 1)).id == mine.id
    assert await dm.find_subscription_for_url(db_session, normalize_download_url(mine.url), 2) is None
    assert await dm.find_subscription_for_url(db_session, "https://nowhere.example/x", 1) is None


async def test_find_gallery_subscription_returns_newest_linking_job_of_the_owner(db_session):
    gallery = await add_gallery(db_session)
    old_sub = await add_subscription(db_session, url="https://x.com/old")
    new_sub = await add_subscription(db_session, url="https://x.com/new")
    foreign_sub = await add_subscription(db_session, user_id=2, url="https://x.com/foreign")
    for sub, day in ((old_sub, 1), (new_sub, 2)):
        await add_job(
            db_session,
            url=normalize_download_url(sub.url),
            gallery_id=gallery.id,
            subscription_id=sub.id,
            status="done",
            created_at=utc(2026, 10, day),
        )

    assert (await dm.find_gallery_subscription(db_session, gallery.id, 1)).id == new_sub.id
    assert await dm.find_gallery_subscription(db_session, gallery.id, 3) is None
    # A job of another user's subscription never makes the gallery "theirs".
    await add_job(
        db_session,
        url=normalize_download_url(foreign_sub.url),
        gallery_id=gallery.id,
        subscription_id=foreign_sub.id,
        status="done",
        created_at=utc(2026, 10, 3),
    )
    assert (await dm.find_gallery_subscription(db_session, gallery.id, 1)).id == new_sub.id


async def test_find_gallery_subscription_ignores_per_work_job_galleries(db_session):
    """A per-work gallery (one Fanbox post) carries a subscription_id, but its job URL is the post, not the creator.

    Repairing it with the creator URL, or running a creator check for "update", would not touch that post.
    """
    gallery = await add_gallery(db_session)
    sub = await add_subscription(db_session, url="https://creator.fanbox.cc/")
    await add_job(
        db_session,
        url="https://creator.fanbox.cc/posts/12345",  # the post, not the subscription URL
        gallery_id=gallery.id,
        subscription_id=sub.id,
        status="done",
    )

    assert await dm.find_gallery_subscription(db_session, gallery.id, 1) is None
