"""worker.download_stop.finalize_stopped_job: finishing a stop-requested job nobody is executing."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.events import EventType
from tests._download_stop_support import add_job, utc

STOP_AT = utc(2026, 10, 30, 10, 0)
RUN_START = utc(2026, 10, 30, 9, 0)


@pytest.fixture
def env(db_session_factory):
    ns = MagicMock()
    ns.set_sub = AsyncMock()
    ns.emit = AsyncMock()
    ns.publish = AsyncMock()
    ns.keep = AsyncMock(return_value=7)
    with (
        patch("worker.download_stop.AsyncSessionLocal", db_session_factory),
        patch("worker.download_stop._set_subscription_result", ns.set_sub),
        patch("worker.download_stop.emit_safe", ns.emit),
        patch("worker.download_stop.publish_job_event", ns.publish),
        patch("worker.download_stop._keep_gallery", ns.keep),
    ):
        yield ns


def _ctx():
    return {"redis": AsyncMock()}


async def test_finalize_stopped_job_ignores_job_with_live_token(db_session, env):
    """A token means a live execution that runs its own keep path; finishing it here would race it."""
    from worker.download_stop import finalize_stopped_job

    job = await add_job(db_session, status="running", stop_requested_at=STOP_AT, admission_token=uuid.uuid4())

    assert await finalize_stopped_job(_ctx(), str(job.id)) == {"status": "ignored"}

    await db_session.refresh(job)
    assert job.status == "running"
    env.keep.assert_not_awaited()
    env.set_sub.assert_not_awaited()


async def test_finalize_stopped_job_finishes_paused_job_without_execution(db_session, env):
    from worker.download_stop import finalize_stopped_job

    job = await add_job(
        db_session,
        status="paused",
        mode="subscription_incremental",
        gallery_id=None,
        stop_requested_at=STOP_AT,
        progress={"started_at": RUN_START.isoformat(), "downloaded": 4},
    )
    ctx = _ctx()

    out = await finalize_stopped_job(ctx, str(job.id))

    assert out == {"status": "done", "outcome": "stopped", "gallery_id": 7}
    await db_session.refresh(job)
    assert job.status == "done" and job.finished_at is not None
    assert job.progress["outcome"] == "stopped" and job.progress["downloaded"] == 4  # earlier progress is kept
    # The boundary is the run's own start (progress.started_at), not the stop click.
    env.set_sub.assert_awaited_once_with(str(job.id), "stopped", boundary=RUN_START)
    env.emit.assert_awaited_once_with(EventType.GALLERY_UPDATED, resource_type="gallery", resource_id=7)
    ctx["redis"].delete.assert_awaited_once()  # stop flag + pause flag cleared


async def test_finalize_stopped_job_boundary_falls_back_to_stop_time_for_a_job_that_never_started(db_session, env):
    from worker.download_stop import finalize_stopped_job

    job = await add_job(db_session, status="queued", mode="subscription_initial", stop_requested_at=STOP_AT)

    await finalize_stopped_job(_ctx(), str(job.id))

    assert env.set_sub.await_args.kwargs["boundary"].replace(tzinfo=None) == STOP_AT.replace(tzinfo=None)


async def test_finalize_stopped_job_second_delivery_is_ignored(db_session, env):
    from worker.download_stop import finalize_stopped_job

    job = await add_job(db_session, status="paused", stop_requested_at=STOP_AT)

    first = await finalize_stopped_job(_ctx(), str(job.id))
    second = await finalize_stopped_job(_ctx(), str(job.id))

    assert first["status"] == "done" and second == {"status": "ignored"}
    env.set_sub.assert_awaited_once()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"status": "running", "stop_requested_at": None},  # no intent
        {"status": "done", "stop_requested_at": STOP_AT},
        {"status": "cancelled", "stop_requested_at": STOP_AT},  # cancel after stop discarded it
        {"status": "failed", "stop_requested_at": STOP_AT},
    ],
    ids=["no-intent", "done", "cancelled", "failed"],
)
async def test_finalize_stopped_job_ignores_jobs_it_must_not_touch(db_session, env, kwargs):
    from worker.download_stop import finalize_stopped_job

    job = await add_job(db_session, **kwargs)

    assert await finalize_stopped_job(_ctx(), str(job.id)) == {"status": "ignored"}
    await db_session.refresh(job)
    assert job.status == kwargs["status"]
    env.keep.assert_not_awaited()


async def test_finalize_stopped_job_ignores_missing_or_malformed_id(env):
    from worker.download_stop import finalize_stopped_job

    assert await finalize_stopped_job(_ctx(), str(uuid.uuid4())) == {"status": "ignored"}
    assert await finalize_stopped_job(_ctx(), "not-a-uuid") == {"status": "ignored"}


# ── _keep_gallery ───────────────────────────────────────────────────────


def _row(**over):
    base = dict(
        id=uuid.uuid4(),
        url="https://e-hentai.org/g/1/abcdef0123/",
        status="paused",
        user_id=1,
        gallery_id=7,
        options={},
    )
    return MagicMock(**{**base, **over})


def _keep_env(tmp_path, importer):
    plugin = MagicMock()
    plugin.meta.source_id = "ehentai"
    return (
        patch("worker.progressive.ProgressiveImporter", MagicMock(return_value=importer)),
        patch("worker.progressive._rmtree_staging_dir", MagicMock()),
        patch("worker.download_stop._resolve_target", AsyncMock(return_value=(plugin, tmp_path))),
        patch("worker.download_stop._import_staged_leftovers", AsyncMock(return_value=0)),
    )


def _imp(*, attached=True, trashed=False):
    imp = MagicMock()
    imp.skipped_trashed = trashed
    imp.title = "T"
    imp.import_failures = ()
    imp.import_success_count = 3
    imp.attach_existing_gallery = AsyncMock(return_value=attached)
    imp.finalize_kept = AsyncMock(return_value=7)
    imp.discard_unlinked_archive_entries = AsyncMock()
    imp.abort = AsyncMock()
    return imp


async def test_keep_gallery_job_that_never_ran_has_nothing_to_keep(tmp_path):
    """No gallery and an empty staging dir: nothing to keep and no gallery to touch."""
    from worker.download_stop import _keep_gallery

    imp = _imp()
    patches = _keep_env(tmp_path, imp)
    with patches[0], patches[1] as rmtree, patches[2], patches[3]:
        assert await _keep_gallery("j", _row(status="queued", gallery_id=None), {}, "download", {}) is None

    imp.attach_existing_gallery.assert_not_awaited()
    imp.finalize_kept.assert_not_awaited()
    rmtree.assert_not_called()


async def test_keep_gallery_requeued_job_with_staged_files_is_still_judged_from_the_data(tmp_path):
    """Status is not the signal: a job that ran can be `queued` again (retry/resume) with its staging intact."""
    from worker.download_stop import _keep_gallery

    (tmp_path / "001.jpg").write_bytes(b"x")
    imp = _imp(attached=False)
    patches = _keep_env(tmp_path, imp)
    with patches[0], patches[1] as rmtree, patches[2], patches[3]:
        assert await _keep_gallery("j", _row(status="queued", gallery_id=None), {}, "download", {}) is None

    imp.discard_unlinked_archive_entries.assert_awaited_once()  # it went past the early return
    rmtree.assert_called_once_with(tmp_path)


async def test_keep_gallery_finalizes_the_attached_gallery_with_the_job_mode(tmp_path):
    from worker.download_stop import _keep_gallery

    imp = _imp()
    patches = _keep_env(tmp_path, imp)
    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3] as leftovers,
        patch("worker.download_stop._record_kept", AsyncMock()),
    ):
        gallery_id = await _keep_gallery("j", _row(), {}, "subscription_incremental", {})

    assert gallery_id == 7
    leftovers.assert_awaited_once()
    imp.finalize_kept.assert_awaited_once_with(tmp_path, mode="subscription_incremental")


@pytest.mark.parametrize("attached,trashed", [(False, False), (True, True)], ids=["no-gallery", "trashed-gallery"])
async def test_keep_gallery_without_a_live_gallery_discards_archive_rows_and_staging(tmp_path, attached, trashed):
    from worker.download_stop import _keep_gallery

    imp = _imp(attached=attached, trashed=trashed)
    patches = _keep_env(tmp_path, imp)
    with patches[0], patches[1] as rmtree, patches[2], patches[3]:
        assert await _keep_gallery("j", _row(), {}, "download", {}) is None

    imp.discard_unlinked_archive_entries.assert_awaited_once()
    imp.finalize_kept.assert_not_awaited()
    rmtree.assert_called_once_with(tmp_path)


async def test_keep_gallery_failure_aborts_instead_of_raising(tmp_path):
    """The job is already `done` when this runs, so a failure is logged and left to reconciliation."""
    from worker.download_stop import _keep_gallery

    imp = _imp()
    imp.finalize_kept = AsyncMock(side_effect=RuntimeError("db gone"))
    patches = _keep_env(tmp_path, imp)
    with patches[0], patches[1], patches[2], patches[3]:
        assert await _keep_gallery("j", _row(), {}, "download", {}) is None

    imp.abort.assert_awaited_once()


async def test_finalize_stopped_job_moves_boundary_even_if_gallery_work_raises(db_session, env):
    """The job is already `done` when the gallery work runs, so nothing would redo a boundary skipped by a failure."""
    from worker.download_stop import finalize_stopped_job

    job = await add_job(
        db_session,
        status="paused",
        mode="subscription_incremental",
        stop_requested_at=STOP_AT,
        progress={"started_at": RUN_START.isoformat()},
    )
    boundary_moved_before_keep: list[bool] = []

    async def _keep_raises(*args, **kwargs):
        boundary_moved_before_keep.append(env.set_sub.await_count == 1)
        raise RuntimeError("keep blew up")

    env.keep.side_effect = _keep_raises

    with pytest.raises(RuntimeError, match="keep blew up"):
        await finalize_stopped_job(_ctx(), str(job.id))

    assert boundary_moved_before_keep == [True]
    env.set_sub.assert_awaited_once_with(str(job.id), "stopped", boundary=RUN_START)
    await db_session.refresh(job)
    assert job.status == "done"
