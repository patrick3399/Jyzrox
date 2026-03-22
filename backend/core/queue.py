"""SAQ queue abstraction layer."""

from __future__ import annotations

import logging
from typing import Any

from saq import Queue

from core.config import settings

logger = logging.getLogger(__name__)

_queue: Queue | None = None


# ---------------------------------------------------------------------------
# Queue lifecycle
# ---------------------------------------------------------------------------


async def init_queue(redis_url: str | None = None) -> Queue:
    """Initialize the global SAQ Queue instance."""
    global _queue
    if _queue is not None:
        return _queue
    url = redis_url or settings.redis_url
    _queue = Queue.from_url(url)
    await _queue.connect()
    logger.info("SAQ queue connected")
    return _queue


async def close_queue() -> None:
    """Disconnect and clean up the global SAQ Queue."""
    global _queue
    if _queue is not None:
        await _queue.disconnect()
        _queue = None
        logger.info("SAQ queue disconnected")


def get_queue() -> Queue:
    """Return the global SAQ Queue. Raises if not initialized."""
    if _queue is None:
        raise RuntimeError("SAQ queue not initialized — call init_queue() first")
    return _queue


# ---------------------------------------------------------------------------
# Enqueue (kwargs-only)
# ---------------------------------------------------------------------------


async def enqueue(
    job_name: str,
    *,  # force kwargs only
    _job_id: str | None = None,
    **kwargs: Any,
) -> Any:
    """Enqueue a job using SAQ.

    All job parameters must be passed as keyword arguments.

    Usage:
        await enqueue("download_job", url=url, source=source, db_job_id=str(job_id), _job_id=str(job_id))
    """
    q = get_queue()
    enqueue_kwargs: dict[str, Any] = {}
    if _job_id is not None:
        enqueue_kwargs["key"] = _job_id
    if kwargs:
        enqueue_kwargs["kwargs"] = kwargs
    return await q.enqueue(job_name, **enqueue_kwargs)
