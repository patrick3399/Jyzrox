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
