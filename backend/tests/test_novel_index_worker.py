"""Tests for worker.novel_index — the knowledge-index refresh cron job."""

from unittest.mock import AsyncMock, patch


async def test_index_job_skips_when_flag_disabled():
    from worker import novel_index as job

    with (
        patch.object(job, "get_toggle", AsyncMock(return_value=False)) as gt,
        patch.object(job, "reindex_all", AsyncMock()) as ri,
    ):
        await job.novel_index_job({"redis": AsyncMock()})
        gt.assert_awaited()
        ri.assert_not_called()


async def test_index_job_registered_in_catalog():
    from core.scheduled_task_catalog import CATALOG

    ids = {t.task_id for t in CATALOG}
    assert "novel_index" in ids


async def test_index_job_warns_when_the_corpus_drifts():
    """Drift must reach the worker log; a stats dict nobody reads is no signal."""
    from unittest.mock import MagicMock

    from worker import novel_index as job

    health = {"stray_root_files": ["作品A/x.md"], "chapters_with_format_issues": 0, "entities_without_mentions": []}
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.commit = AsyncMock()
    with (
        patch.object(job, "get_toggle", AsyncMock(return_value=True)),
        patch.object(job, "acquire_lock", AsyncMock(return_value="token")),
        patch.object(job, "release_lock", AsyncMock()),
        patch.object(job, "_cron_record", AsyncMock()),
        patch.object(job, "async_session", MagicMock(return_value=session)),
        patch.object(
            job, "reindex_all", AsyncMock(return_value={"notes": 0, "links": 0, "mentions": 0, "health": health})
        ),
        patch.object(job.logger, "warning") as warn,
    ):
        await job.novel_index_job({"redis": AsyncMock()}, force=True)
    assert any("作品A/x.md" in str(call.args) for call in warn.call_args_list)
