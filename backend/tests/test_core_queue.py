from unittest.mock import AsyncMock

import core.queue


async def test_enqueue_applies_safe_default_timeout(monkeypatch):
    queue = AsyncMock()
    monkeypatch.setattr(core.queue, "get_queue", lambda _name: queue)

    await core.queue._enqueue_routed("tag_job", gallery_id=42)

    queue.enqueue.assert_awaited_once_with(
        "tag_job",
        timeout=core.queue.DEFAULT_JOB_TIMEOUT,
        kwargs={"gallery_id": 42},
    )


async def test_enqueue_preserves_explicit_timeout(monkeypatch):
    queue = AsyncMock()
    monkeypatch.setattr(core.queue, "get_queue", lambda _name: queue)

    await core.queue._enqueue_routed("rescan_library_job", _job_id="rescan", _timeout=7200)

    queue.enqueue.assert_awaited_once_with(
        "rescan_library_job",
        key="rescan",
        timeout=7200,
    )


async def test_enqueue_preserves_scheduled_and_ttl_transport_options(monkeypatch):
    """Delayed admission retries must reach SAQ as transport options.

    These underscore-prefixed values belong to SAQ itself; placing them inside
    the job payload would make the worker receive unexpected keyword arguments
    and would enqueue the retry immediately instead of scheduling it.
    """
    queue = AsyncMock()
    monkeypatch.setattr(core.queue, "get_queue", lambda _name: queue)

    await core.queue._enqueue_routed(
        "download_job",
        _job_id="dispatch:job-id:attempt-id",
        _scheduled=1_754_000_005,
        _ttl=-1,
        db_job_id="job-id",
    )

    queue.enqueue.assert_awaited_once_with(
        "download_job",
        key="dispatch:job-id:attempt-id",
        timeout=core.queue.DEFAULT_JOB_TIMEOUT,
        scheduled=1_754_000_005,
        ttl=-1,
        kwargs={"db_job_id": "job-id"},
    )
