"""SAQ queue abstraction layer."""

import logging
from typing import Any

from saq import Queue

from core.config import settings
from core.queue_config import ALL_QUEUES, JOB_QUEUE_ROUTING, QUEUE_INTERACTIVE

logger = logging.getLogger(__name__)

_queues: dict[str, Queue] = {}


async def init_queues(redis_url: str | None = None) -> None:
    """Initialize all SAQ Queue instances (one per logical queue)."""
    global _queues
    url = redis_url or settings.redis_url
    for name in ALL_QUEUES:
        q = Queue.from_url(url, name=name)
        await q.connect()
        _queues[name] = q
    logger.info("SAQ queues connected: %s", list(_queues))


# Backward-compat alias — main.py and conftest call init_queue()
init_queue = init_queues


async def close_queues() -> None:
    """Disconnect all SAQ Queue instances."""
    for q in _queues.values():
        await q.disconnect()
    _queues.clear()
    logger.info("SAQ queues disconnected")


# Backward-compat alias — main.py calls close_queue()
close_queue = close_queues


def get_queue(name: str = QUEUE_INTERACTIVE) -> Queue:
    """Return a SAQ Queue by name. Defaults to the interactive queue."""
    if not _queues:
        raise RuntimeError("SAQ queues not initialized — call init_queues() first")
    if name not in _queues:
        raise KeyError(f"Unknown queue '{name}'. Available: {list(_queues)}")
    return _queues[name]


def get_all_queues() -> dict[str, Queue]:
    """Return all initialized Queue instances keyed by name."""
    return dict(_queues)


async def enqueue(
    job_name: str,
    *,
    _job_id: str | None = None,
    _timeout: int | None = None,
    **kwargs: Any,
) -> Any:
    """Enqueue a job, routing to the correct queue automatically.

    Routing is defined in core.queue_config.JOB_QUEUE_ROUTING.
    Jobs not listed there go to the interactive queue.
    """
    queue_name = JOB_QUEUE_ROUTING.get(job_name, QUEUE_INTERACTIVE)
    q = get_queue(queue_name)
    enqueue_kwargs: dict[str, Any] = {}
    if _job_id is not None:
        enqueue_kwargs["key"] = _job_id
    if _timeout is not None:
        enqueue_kwargs["timeout"] = _timeout
    if kwargs:
        enqueue_kwargs["kwargs"] = kwargs
    return await q.enqueue(job_name, **enqueue_kwargs)
