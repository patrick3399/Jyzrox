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
