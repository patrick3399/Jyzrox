"""Regression: 0-downloaded + 0-skipped subscription run must NOT advance
``Subscription.last_success_at``.

Real incident: sub 7 (nidemiaozai/Twitter) had ``date-after`` set from a prior
``last_success_at``. gallery-dl filter-rejected every timeline item (no skip,
no download) and returned 0/0. download.py treated this as "done", advancing
``last_success_at`` to NOW. Next renew's cutoff advanced another day,
perpetually 0/0 — death spiral.

Fix: ``_set_subscription_result(advance_success=False)`` for 0/0 runs.
"""

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_session_capture():
    """Build a fake AsyncSession that captures UPDATE .values() into ``captured``."""
    captured: dict = {}

    fake_session = AsyncMock()
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=None)

    fake_job = MagicMock()
    fake_job.subscription_id = 7
    fake_session.get = AsyncMock(return_value=fake_job)

    async def fake_execute(stmt, *_args, **_kwargs):
        captured["values"] = stmt.compile().params
        return MagicMock()

    fake_session.execute = AsyncMock(side_effect=fake_execute)
    fake_session.commit = AsyncMock()
    return fake_session, captured


@pytest.mark.asyncio
async def test_zero_zero_subscription_done_does_not_advance_last_success_at(monkeypatch):
    import core.database as cdb
    from worker import download as dl_mod

    fake_session, captured = _make_session_capture()
    monkeypatch.setattr(cdb, "AsyncSessionLocal", MagicMock(return_value=fake_session))

    db_job_id = str(uuid.uuid4())
    await dl_mod._set_subscription_result(db_job_id, "done", error=None, advance_success=False)

    assert "last_status" in captured["values"]
    assert captured["values"]["last_status"] == "done"
    # Critical: advance_success=False must NOT include last_success_at
    assert "last_success_at" not in captured["values"], (
        f"0/0 run should not advance last_success_at, got: {captured['values']}"
    )


@pytest.mark.asyncio
async def test_normal_done_still_advances_last_success_at(monkeypatch):
    """Sanity: advance_success=True (default) keeps existing behavior."""
    import core.database as cdb
    from worker import download as dl_mod

    fake_session, captured = _make_session_capture()
    monkeypatch.setattr(cdb, "AsyncSessionLocal", MagicMock(return_value=fake_session))

    db_job_id = str(uuid.uuid4())
    await dl_mod._set_subscription_result(db_job_id, "done")

    assert captured["values"]["last_status"] == "done"
    assert "last_success_at" in captured["values"]
    assert isinstance(captured["values"]["last_success_at"], datetime)


@pytest.mark.asyncio
async def test_subscription_zero_download_due_to_filter_does_not_advance_last_success():
    """BE-T12 with a media policy: everything filtered out (0 downloaded, 0 skipped)
    must not advance ``last_success_at``.

    A policy such as ``include_videos=False`` on a video-only account makes
    gallery-dl emit nothing. The run is "done" but proves nothing was checked, so
    treating it as success would move the incremental cutoff past unseen items.
    """
    from unittest.mock import patch

    from tests.helpers import make_mock_site_config_svc
    from worker.download import download_job

    plugin_result = MagicMock()
    plugin_result.status = "done"
    plugin_result.downloaded = 0
    plugin_result.total = 0
    plugin_result.error = None
    plugin_result.failed_pages = []

    plugin = MagicMock()
    plugin.meta.source_id = "gallery_dl"
    plugin.meta.name = "Gallery-DL"
    plugin.meta.semaphore_key = None
    plugin.meta.needs_all_credentials = False
    plugin.meta.concurrency = 1
    plugin.download = AsyncMock(return_value=plugin_result)

    importer = MagicMock()
    importer.gallery_id = None
    importer.title = ""
    importer.source_url = None
    importer.download_status = None
    importer.import_file = AsyncMock()
    importer.ensure_gallery_from_url = AsyncMock()
    importer.ensure_gallery = AsyncMock()
    importer.finalize = AsyncMock(return_value=None)
    importer.abort = AsyncMock()
    importer.cleanup = AsyncMock()

    registry = MagicMock()
    registry.get_handler = AsyncMock(return_value=plugin)
    registry.get_fallback = MagicMock(return_value=None)
    registry.get_downloader = MagicMock(return_value=None)

    admission = MagicMock()
    admission.claim = AsyncMock(return_value=MagicMock(acquired=True, token=uuid.uuid4(), queue_position=None))
    admission.release = AsyncMock(return_value=True)
    admission.token_is_valid = AsyncMock(return_value=True)

    session = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
    session.get = AsyncMock(return_value=None)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)

    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock(return_value=True)
    redis.delete = AsyncMock(return_value=1)

    options = {"job_context": "subscription", "media": {"max_files": 20, "include_videos": False}}
    with (
        patch("plugins.registry.plugin_registry", registry),
        patch("worker.download.get_credential", new_callable=AsyncMock, return_value=None),
        patch("worker.download._set_job_status", new_callable=AsyncMock),
        patch("worker.download._set_job_progress", new_callable=AsyncMock),
        patch("worker.download._set_subscription_result", new_callable=AsyncMock) as set_result,
        patch("core.database.AsyncSessionLocal", return_value=session),
        patch("worker.progressive.ProgressiveImporter", return_value=importer),
        patch("worker.download.DownloadAdmission", return_value=admission),
        patch("core.redis_client.get_redis", return_value=MagicMock()),
        patch("worker.helpers._validate_image_magic", return_value=True),
        patch("pathlib.Path.exists", return_value=False),
        patch("core.site_config.site_config_service", make_mock_site_config_svc()),
    ):
        result = await download_job(
            {"redis": redis},
            "https://x.com/someuser",
            options=options,
            db_job_id=str(uuid.uuid4()),
        )

    assert result["status"] == "done"
    # The policy reached the plugin, so this really is the media-policy run.
    assert plugin.download.await_args.kwargs["options"]["media"] == options["media"]
    set_result.assert_awaited_once()
    assert set_result.await_args.args[1] == "done"
    assert set_result.await_args.kwargs["advance_success"] is False
