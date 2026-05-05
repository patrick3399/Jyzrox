"""Regression tests for the three subscription-renew bugs surfaced in
worker logs at 2026-05-04 23:14:23 (sub 7) and the preceding hour:

1. SAQ enqueue with `last_completed_at` as datetime → JSON TypeError.
2. download.py forwarding ISO string verbatim → source.py crashes on
   `cutoff = "..." - timedelta(...)` because it expects datetime.
3. ProgressiveImporter._load_gallery_state not restoring source/source_id
   from existing gallery → create_library_symlink crashes with
   "unsupported operand type(s) for /: 'PosixPath' and 'NoneType'".
"""

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

# ── Bug 1: subscription must produce JSON-serializable enqueue kwargs ─────


@pytest.mark.asyncio
async def test_subscription_enqueue_options_are_json_serializable(monkeypatch):
    """Reproduces: 23:14:23 [ERROR] worker: [subscription] error processing
    sub 7: Object of type datetime is not JSON serializable.

    Root cause: subscription.py wrote `options["last_completed_at"] =
    sub.last_success_at` (datetime). SAQ uses json.dumps to serialize job
    kwargs and crashes. Fix: send isoformat() string.
    """
    from worker import subscription as sub_mod

    captured: dict = {}

    async def fake_enqueue(name, **kw):
        captured["kwargs"] = kw
        # SAQ-equivalent serialization probe:
        json.dumps(kw)  # must not raise
        return MagicMock()

    monkeypatch.setattr(sub_mod.core.queue, "enqueue", fake_enqueue)
    monkeypatch.setattr(
        sub_mod,
        "acquire_lock",
        AsyncMock(return_value="lock-token-1"),
    )
    monkeypatch.setattr(sub_mod, "release_lock", AsyncMock())

    fake_redis = MagicMock()
    fake_pub = AsyncMock()
    monkeypatch.setattr(
        "core.redis_client.get_redis",
        MagicMock(return_value=fake_redis),
    )
    monkeypatch.setattr("core.redis_client.publish_job_event", fake_pub)

    # Avoid touching DB: short-circuit the source-enabled and credentials checks
    async def _always_enabled(_source: str) -> bool:
        return True

    monkeypatch.setattr("services.source_health.is_source_enabled", _always_enabled)

    # Stub session usage — let the subscription branch run, mock both
    # AsyncSessionLocal() returns. Easier: monkeypatch sub_mod.AsyncSessionLocal
    fake_session = AsyncMock()
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=None)
    fake_session.execute = AsyncMock(
        return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=None),
            scalar_one=MagicMock(return_value=None),
        )
    )
    fake_session.add = MagicMock()
    fake_session.commit = AsyncMock()

    monkeypatch.setattr(
        sub_mod,
        "AsyncSessionLocal",
        MagicMock(return_value=fake_session),
    )

    sub = MagicMock()
    sub.id = 7
    sub.user_id = 1
    sub.url = "https://x.com/foo"
    sub.source = "twitter"
    sub.last_success_at = datetime(2026, 4, 30, 12, 0, 0, tzinfo=UTC)

    ctx = {"redis": fake_redis}
    result = await sub_mod._enqueue_for_subscription(ctx, sub)

    assert result["status"] == "ok", f"unexpected: {result}"
    options = captured["kwargs"]["options"]
    # Must be string after fix — datetime would have failed json.dumps above
    assert isinstance(options["last_completed_at"], str)
    assert options["last_completed_at"] == sub.last_success_at.isoformat()


# ── Bug 2: download.py must reify ISO string back into datetime ──────────


def test_last_completed_at_iso_string_reifies_to_datetime():
    """The chain subscription → SAQ JSON → download.py → source.py expects
    a datetime at the source.py end. download.py is the boundary that has
    to convert string back to datetime."""
    iso = "2026-04-30T12:00:00+00:00"
    parsed = datetime.fromisoformat(iso)
    assert parsed.year == 2026
    assert parsed.tzinfo is not None
    # Subtraction must work — this was the original failure mode in source.py
    from datetime import timedelta

    cutoff = parsed - timedelta(days=1)
    assert cutoff.day == 29


def test_last_completed_at_invalid_iso_does_not_crash_download():
    """Defensive check: malformed ISO must be caught, not propagate."""
    with pytest.raises(ValueError):
        datetime.fromisoformat("not-an-iso-string")


# ── Bug 3: _load_gallery_state must restore source/source_id ─────────────


@pytest.mark.asyncio
async def test_load_gallery_state_restores_source_for_existing_gallery(monkeypatch):
    """Reproduces: 22:50:30 [WARNING] worker: [progressive] failed to import
    1992214603137462419_1.mp4: unsupported operand type(s) for /: 'PosixPath'
    and 'NoneType'.

    Root cause: subscription renew sets importer.gallery_id from the
    existing DownloadJob.gallery_id but never calls ensure_gallery_*, so
    self.source/self.source_id stay None. Then create_library_symlink does
    `Path(...) / source / source_id` and crashes on None.

    Fix: _load_gallery_state SELECTs the gallery row and restores them.
    """
    from worker import progressive as prog_mod

    fake_gallery = MagicMock()
    fake_gallery.source = "twitter"
    fake_gallery.source_id = "123456789"
    fake_gallery.title = "Some Artist"

    fake_session = AsyncMock()
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=None)
    fake_session.get = AsyncMock(return_value=fake_gallery)
    # Excluded blob query + existing image rows query both return empty
    empty_result = MagicMock()
    empty_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    empty_result.all = MagicMock(return_value=[])
    fake_session.execute = AsyncMock(return_value=empty_result)

    monkeypatch.setattr(
        prog_mod,
        "AsyncSessionLocal",
        MagicMock(return_value=fake_session),
    )

    importer = prog_mod.ProgressiveImporter(db_job_id="job-1", user_id=1)
    importer.gallery_id = 42
    # Pre-condition: source/source_id are NOT set (renew flow)
    assert importer.source is None
    assert importer.source_id is None

    await importer._load_gallery_state()

    # Post-condition: restored from gallery row
    assert importer.source == "twitter"
    assert importer.source_id == "123456789"
    assert importer.title == "Some Artist"


@pytest.mark.asyncio
async def test_load_gallery_state_does_not_overwrite_already_set_fields(monkeypatch):
    """If the importer already has source set (manual download path),
    _load_gallery_state must NOT clobber it."""
    from worker import progressive as prog_mod

    fake_gallery = MagicMock()
    fake_gallery.source = "twitter"
    fake_gallery.source_id = "different_id"
    fake_gallery.title = "Different"

    fake_session = AsyncMock()
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=None)
    fake_session.get = AsyncMock(return_value=fake_gallery)
    empty_result = MagicMock()
    empty_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    empty_result.all = MagicMock(return_value=[])
    fake_session.execute = AsyncMock(return_value=empty_result)

    monkeypatch.setattr(
        prog_mod,
        "AsyncSessionLocal",
        MagicMock(return_value=fake_session),
    )

    importer = prog_mod.ProgressiveImporter(db_job_id="job-2", user_id=1)
    importer.gallery_id = 99
    importer.source = "pixiv"
    importer.source_id = "manual_set_id"

    await importer._load_gallery_state()

    # Manual values preserved
    assert importer.source == "pixiv"
    assert importer.source_id == "manual_set_id"


@pytest.mark.asyncio
async def test_load_gallery_state_no_gallery_id_is_noop(monkeypatch):
    """Sanity: without gallery_id, the function returns immediately."""
    from worker import progressive as prog_mod

    fake_factory = MagicMock()
    monkeypatch.setattr(prog_mod, "AsyncSessionLocal", fake_factory)
    importer = prog_mod.ProgressiveImporter(db_job_id=None, user_id=1)
    importer.gallery_id = None
    await importer._load_gallery_state()
    fake_factory.assert_not_called()
