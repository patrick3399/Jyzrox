"""Which SAQ worker consumes which queue (worker.build_workers)."""

import pytest

from core.queue_config import QUEUE_COVER, QUEUE_INGEST


@pytest.fixture
def workers_by_queue(monkeypatch):
    import core.queue as core_queue
    from worker import build_workers

    monkeypatch.setattr(core_queue, "_queues", dict(core_queue._queues))
    return {w.queue.name: w for w in build_workers()}


def test_cover_queue_has_a_worker_that_runs_cover_thumbnail_job(workers_by_queue):
    assert QUEUE_COVER in workers_by_queue, "jobs routed to a queue nobody consumes would never run"
    assert set(workers_by_queue[QUEUE_COVER].functions) == {"cover_thumbnail_job"}


def test_ingest_worker_still_runs_cover_jobs_queued_before_the_cover_queue_existed(workers_by_queue):
    """Cover jobs already sitting in `ingest` at deploy time, or enqueued by an
    api container still on the old routing, must drain instead of failing."""
    assert "cover_thumbnail_job" in workers_by_queue[QUEUE_INGEST].functions
