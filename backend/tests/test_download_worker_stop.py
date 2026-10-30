"""Worker keep path for a user stop: _run_download_job -> _finish_stopped, and the subscription boundary rules.

SQLite cannot run ``GREATEST`` or ``SELECT ... FOR UPDATE``: the boundary rules are asserted on the compiled
PostgreSQL statement and on the values handed to it (see the report for what still needs a real Postgres).
"""

from contextlib import ExitStack
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.dialects import postgresql

from core.events import EventType
from core.site_config import DownloadParams
from tests._download_stop_support import EH_URL, add_job, utc

STARTED = utc(2026, 10, 30, 9, 0)


def _importer(*, gallery_id=42, success=3, trashed=False):
    imp = MagicMock()
    imp.gallery_id = gallery_id
    imp.title = "Gallery title"
    imp.skipped_trashed = trashed
    imp.existing_page_nums = set()
    imp.import_failures = ()
    imp.import_success_count = success
    imp.skipped_duplicate_count = imp.skipped_excluded_count = imp.skipped_invalid_count = 0
    imp.repair_archive = None
    imp.has_processed = MagicMock(return_value=False)
    for name in ("import_file", "abort", "cleanup", "discard_unlinked_archive_entries"):
        setattr(imp, name, AsyncMock())
    imp.finalize_kept = AsyncMock(return_value=gallery_id)
    imp.finalize = AsyncMock(return_value=gallery_id)
    imp.attach_existing_gallery = AsyncMock(return_value=True)
    return imp


async def _db_status(factory, job_id):
    from db.models import DownloadJob

    async with factory() as s:
        return (await s.get(DownloadJob, job_id)).status


def _result(status, downloaded=2, error=None):
    return MagicMock(status=status, downloaded=downloaded, total=downloaded, error=error, failed_pages=[])


async def _flag_stop(factory, job_id):
    from db.models import DownloadJob

    async with factory() as s:
        row = await s.get(DownloadJob, job_id)
        row.stop_requested_at = utc(2026, 10, 30, 9, 30)
        await s.commit()


async def _run(db_session_factory, tmp_path, job, importer, plugin_download):
    """Run the real _run_download_job with the plugin and importer faked and stop intent read from SQLite."""
    from worker.download import _run_download_job

    plugin = MagicMock()
    plugin.meta.source_id = "ehentai"
    plugin.meta.name = "E-Hentai"
    plugin.meta.concurrency = 1
    plugin.meta.needs_all_credentials = False
    del plugin.resolve_metadata
    plugin.download = AsyncMock(side_effect=plugin_download)
    registry = MagicMock()
    registry.get_downloader = MagicMock(return_value=None)

    h = SimpleNamespace(
        importer=importer,
        plugin=plugin,
        set_status=AsyncMock(),
        set_progress=AsyncMock(),
        set_sub=AsyncMock(),
        emit=AsyncMock(),
        finalize_enqueue=AsyncMock(),
        rmtree=MagicMock(),
        target_dir=tmp_path / str(job.id),
    )
    with ExitStack() as stack:
        for target, value in {
            "plugins.registry.plugin_registry": registry,
            "worker.download.get_credential": AsyncMock(return_value=None),
            "worker.download._set_job_status": h.set_status,
            "worker.download._set_job_progress": h.set_progress,
            "worker.download._set_subscription_result": h.set_sub,
            "worker.download.emit_safe": h.emit,
            "worker.download.enqueue_finalize_stopped_job": h.finalize_enqueue,
            "worker.download.check_disk_space": MagicMock(return_value=(True, 100.0)),
            "worker.download.settings": MagicMock(data_gallery_path=str(tmp_path), disk_min_free_gb=1),
            "core.database.AsyncSessionLocal": db_session_factory,
            "services.download_stop.AsyncSessionLocal": db_session_factory,
            "worker.progressive.ProgressiveImporter": MagicMock(return_value=importer),
            "worker.progressive._rmtree_staging_dir": h.rmtree,
        }.items():
            stack.enter_context(patch(target, value))
        h.outcome = await _run_download_job(
            {"redis": AsyncMock(get=AsyncMock(return_value=None))},
            job.url,
            "ehentai",
            job.options,
            str(job.id),
            None,
            plugin=plugin,
            dl_params=DownloadParams(),
            admission_token=None,
        )
    return h


def _stop_during_run(factory, job, result, *, stage=None):
    async def _download(**kwargs):
        if stage:
            stage(kwargs["dest_dir"])
        await _flag_stop(factory, job.id)
        return result

    return _download


# ── keep path ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("mode", ["download", "subscription_initial", "subscription_incremental", "repair"])
async def test_stopped_result_keeps_gallery_and_finishes_done(db_session, db_session_factory, tmp_path, mode):
    job = await add_job(db_session, status="running", mode=mode, subscription_id=None)
    imp = _importer()

    h = await _run(
        db_session_factory, tmp_path, job, imp, _stop_during_run(db_session_factory, job, _result("cancelled"))
    )

    assert h.outcome == {"status": "done", "outcome": "stopped", "downloaded": 2}
    imp.finalize_kept.assert_awaited_once_with(h.target_dir, mode=mode)
    imp.cleanup.assert_not_awaited()
    imp.abort.assert_not_awaited()
    assert await _db_status(db_session_factory, job.id) == "done"  # claimed before the gallery was kept
    progress = h.set_progress.await_args_list[-1].args[1]
    assert progress["outcome"] == "stopped"
    assert progress["status_text"] == "Stopped — kept 3"
    assert progress["gallery_id"] == 42
    h.emit.assert_awaited_with(EventType.GALLERY_UPDATED, resource_type="gallery", resource_id=42)


async def test_stopped_subscription_advances_boundary_to_run_start(db_session, db_session_factory, tmp_path):
    """The boundary handed over is the run's own start time, not the moment the user clicked stop."""
    job = await add_job(db_session, status="running", mode="subscription_incremental", subscription_id=None)

    h = await _run(
        db_session_factory, tmp_path, job, _importer(), _stop_during_run(db_session_factory, job, _result("cancelled"))
    )

    h.set_sub.assert_awaited_once()
    assert h.set_sub.await_args.args == (str(job.id), "stopped")
    boundary = h.set_sub.await_args.kwargs["boundary"]
    started_at = h.set_progress.await_args_list[-1].args[1]["started_at"]
    assert boundary.isoformat() == started_at
    assert boundary < utc(2099, 1, 1) and boundary.tzinfo is not None


async def test_stop_with_failed_result_still_keeps(db_session, db_session_factory, tmp_path):
    """A9: the process died at the same moment the user stopped. The stop still wins; nothing is aborted/failed."""
    job = await add_job(db_session, status="running", mode="subscription_incremental")
    imp = _importer()

    h = await _run(
        db_session_factory,
        tmp_path,
        job,
        imp,
        _stop_during_run(db_session_factory, job, _result("failed", error="timeout")),
    )

    assert h.outcome["outcome"] == "stopped"
    imp.finalize_kept.assert_awaited_once()
    imp.abort.assert_not_awaited()
    assert "failed" not in [c.args[1] for c in h.set_status.await_args_list]
    assert await _db_status(db_session_factory, job.id) == "done"
    assert all(c.args[1] != "failed" for c in h.set_sub.await_args_list)


async def test_stop_with_plugin_exception_still_keeps(db_session, db_session_factory, tmp_path):
    job = await add_job(db_session, status="running", mode="download")
    imp = _importer()

    async def _boom(**kwargs):
        await _flag_stop(db_session_factory, job.id)
        raise RuntimeError("pipe closed")

    h = await _run(db_session_factory, tmp_path, job, imp, _boom)

    assert h.outcome["outcome"] == "stopped"
    imp.abort.assert_not_awaited()
    imp.finalize_kept.assert_awaited_once()


async def test_plugin_exception_without_stop_intent_still_fails_the_job(db_session, db_session_factory, tmp_path):
    job = await add_job(db_session, status="running", mode="download")
    imp = _importer()

    async def _boom(**kwargs):
        raise RuntimeError("pipe closed")

    h = await _run(db_session_factory, tmp_path, job, imp, _boom)

    assert h.outcome["status"] == "failed"
    imp.abort.assert_awaited_once()
    imp.finalize_kept.assert_not_awaited()


async def test_run_finished_before_stop_landed_is_not_rewritten_as_stopped(db_session, db_session_factory, tmp_path):
    """A1: a `done` result is simply finished; the late stop must not turn it into a stopped run."""
    job = await add_job(db_session, status="running", mode="download")
    imp = _importer()

    h = await _run(db_session_factory, tmp_path, job, imp, _stop_during_run(db_session_factory, job, _result("done")))

    assert h.outcome["status"] == "done" and "outcome" not in h.outcome
    imp.finalize_kept.assert_not_awaited()


async def test_stop_requested_before_start_never_runs_the_download(db_session, db_session_factory, tmp_path):
    job = await add_job(db_session, status="running", mode="download", stop_requested_at=utc(2026, 10, 30, 8, 0))
    imp = _importer(gallery_id=None)

    h = await _run(db_session_factory, tmp_path, job, imp, _stop_during_run(db_session_factory, job, _result("done")))

    h.plugin.download.assert_not_awaited()
    assert h.outcome["outcome"] == "stopped"


async def test_stop_sweeps_staged_files_not_printed(db_session, db_session_factory, tmp_path):
    """B1: gallery-dl archives a file before it prints it. Finished media nobody printed must reach the importer."""
    job = await add_job(db_session, status="running", mode="download")
    imp = _importer()
    imp.has_processed = MagicMock(side_effect=lambda p: p.name == "002.png")  # 002 was printed and imported

    def _stage(dest):
        dest.mkdir(parents=True, exist_ok=True)
        for name in ("001.jpg", "002.png", "003.jpg.part", ".004.jpg", "005.txt", "006.mp4.tmp"):
            (dest / name).write_bytes(b"x")

    h = await _run(
        db_session_factory,
        tmp_path,
        job,
        imp,
        _stop_during_run(db_session_factory, job, _result("cancelled"), stage=_stage),
    )

    imported = [c.args[0].name for c in imp.import_file.await_args_list]
    assert imported == ["001.jpg"]  # not the printed one, not partial/hidden/non-media files
    imp.finalize_kept.assert_awaited_once()
    assert h.outcome["outcome"] == "stopped"


@pytest.mark.parametrize("trashed", [False, True])
async def test_stop_with_no_gallery_discards_unlinked_archive_rows(db_session, db_session_factory, tmp_path, trashed):
    """E5 (and BE-T17 for a trashed target): nothing to keep -> the run's archive rows must not become holes."""
    job = await add_job(db_session, status="running", mode="subscription_initial")
    imp = _importer(gallery_id=7 if trashed else None, trashed=trashed)

    h = await _run(
        db_session_factory, tmp_path, job, imp, _stop_during_run(db_session_factory, job, _result("cancelled", 0))
    )

    imp.discard_unlinked_archive_entries.assert_awaited_once()
    imp.finalize_kept.assert_not_awaited()
    h.rmtree.assert_called_once_with(h.target_dir)
    assert h.outcome["outcome"] == "stopped"
    assert "gallery_id" not in h.set_progress.await_args_list[-1].args[1]
    h.emit.assert_not_awaited()


async def test_keep_path_failure_before_the_claim_hands_job_to_finalize_stopped_job():
    """If the keep path breaks while the job is still active, it must not be left running: the detached task redoes it."""
    from worker.download import _finish_stopped

    imp = _importer()
    handoff = AsyncMock()
    with (
        patch("worker.download.enqueue_finalize_stopped_job", handoff),
        patch("worker.download._import_staged_leftovers", AsyncMock(return_value=0)),
        patch("worker.download.claim_stop_finish", AsyncMock(side_effect=RuntimeError("db gone"))),
    ):
        out = await _finish_stopped(
            importer=imp,
            target_dir=MagicMock(),
            url=EH_URL,
            plugin=MagicMock(),
            on_file=AsyncMock(),
            db_job_id="0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d",
            mode="download",
            started_at=STARTED,
            boundary=STARTED,
            credentials=None,
            credential_accounts=None,
            result=None,
        )

    assert out["status"] == "stopping"
    handoff.assert_awaited_once_with("0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d")
    imp.finalize_kept.assert_not_awaited()


async def test_keep_failure_after_the_claim_still_moves_the_boundary_and_ends_done(
    db_session, db_session_factory, tmp_path
):
    """Once claimed `done` nothing would redo the boundary, so it moves before the gallery work; a failing keep
    is aborted for reconciliation instead of being handed to a task that would ignore a finished job."""
    job = await add_job(db_session, status="running", mode="subscription_incremental")
    imp = _importer()
    imp.finalize_kept = AsyncMock(side_effect=RuntimeError("db gone"))

    h = await _run(
        db_session_factory, tmp_path, job, imp, _stop_during_run(db_session_factory, job, _result("cancelled"))
    )

    assert h.outcome["outcome"] == "stopped"
    assert await _db_status(db_session_factory, job.id) == "done"
    h.set_sub.assert_awaited_once()
    assert h.set_sub.await_args.args == (str(job.id), "stopped")
    imp.abort.assert_awaited_once()
    h.finalize_enqueue.assert_not_awaited()


# ── stop before start: boundary of a job that never ran ───────────────────


async def test_stop_before_start_of_a_job_that_never_ran_leaves_the_boundary_alone(
    db_session, db_session_factory, tmp_path
):
    """A queued incremental check stopped before it ran fetched nothing; moving the boundary to "now" would
    silently give up every post since the last check."""
    job = await add_job(
        db_session, status="running", mode="subscription_incremental", stop_requested_at=utc(2026, 10, 30, 8, 0)
    )

    h = await _run(
        db_session_factory, tmp_path, job, _importer(gallery_id=None), _stop_during_run(db_session_factory, job, None)
    )

    h.plugin.download.assert_not_awaited()
    h.set_sub.assert_awaited_once_with(str(job.id), "stopped", boundary=None)


async def test_stop_before_start_of_a_resumed_job_uses_the_earlier_run_start(db_session, db_session_factory, tmp_path):
    """A job that already ran once (recovered/resumed) keeps that run's start as its boundary, not this execution's."""
    job = await add_job(
        db_session,
        status="running",
        mode="subscription_incremental",
        stop_requested_at=utc(2026, 10, 30, 8, 0),
        progress={"started_at": STARTED.isoformat()},
    )

    h = await _run(db_session_factory, tmp_path, job, _importer(), _stop_during_run(db_session_factory, job, None))

    h.set_sub.assert_awaited_once_with(str(job.id), "stopped", boundary=STARTED)


# ── _set_subscription_result: boundary and repair rules ─────────────────


def _fake_session(job):
    captured: dict = {}
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.get = AsyncMock(return_value=job)

    async def _execute(stmt, *a, **k):
        captured["stmt"] = stmt
        return MagicMock()

    session.execute = AsyncMock(side_effect=_execute)
    session.commit = AsyncMock()
    return MagicMock(return_value=session), captured


async def _record(job, status, **kwargs):
    from worker.download import _set_subscription_result

    factory, captured = _fake_session(job)
    health = AsyncMock()
    with (
        patch("core.database.AsyncSessionLocal", factory),
        patch("services.subscription_health.record_check_result", health),
    ):
        await _set_subscription_result("0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d", status, **kwargs)
    return captured.get("stmt"), health


def _sub_job(mode="subscription_incremental", options=None):
    return MagicMock(subscription_id=7, mode=mode, options=options or {})


def _pg(stmt):
    compiled = stmt.compile(dialect=postgresql.dialect())
    return str(compiled), compiled.params


async def test_stop_boundary_never_moves_backwards():
    """last_success_at = GREATEST(COALESCE(last_success_at, boundary), boundary): an earlier boundary cannot pull it back."""
    stmt, health = await _record(_sub_job(), "stopped", boundary=STARTED)

    sql, params = _pg(stmt)
    assert "greatest(coalesce(subscriptions.last_success_at" in sql.lower().replace("\n", " ")
    assert [v for v in params.values() if isinstance(v, datetime)] == [STARTED, STARTED]
    assert params["last_status"] == "stopped" and params["last_error"] is None
    health.assert_awaited_once_with(7, "stopped")


async def test_stop_without_boundary_leaves_last_success_at_alone():
    stmt, _ = await _record(_sub_job(), "stopped")

    sql, params = _pg(stmt)
    assert "last_success_at" not in sql.split("WHERE")[0]
    assert params["last_status"] == "stopped"


async def test_done_run_still_advances_last_success_at_to_now():
    stmt, _ = await _record(_sub_job(), "done")

    _, params = _pg(stmt)
    assert isinstance(params["last_success_at"], datetime)


@pytest.mark.parametrize("status", ["done", "stopped", "partial", "failed"])
@pytest.mark.parametrize(
    "job",
    [_sub_job(mode="repair"), _sub_job(mode="download", options={"force_full_scan": True})],
    ids=["stamped-repair", "legacy-force-full-scan"],
)
async def test_repair_job_never_advances_last_success_at(job, status):
    """A repair re-fetches what the subscription already covers; it owns no boundary whatever its status."""
    stmt, health = await _record(job, status, boundary=STARTED, error="x" if status == "failed" else None)

    sql, params = _pg(stmt)
    assert "last_success_at" not in sql.split("WHERE")[0]
    assert params["last_status"] == status  # the status is still recorded
    health.assert_awaited_once_with(7, status)


async def test_job_without_subscription_updates_nothing():
    stmt, health = await _record(MagicMock(subscription_id=None), "stopped", boundary=STARTED)

    assert stmt is None
    health.assert_not_awaited()
