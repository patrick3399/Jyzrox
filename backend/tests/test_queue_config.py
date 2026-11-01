"""Tests for queue routing configuration."""

from core.queue_config import (
    ALL_QUEUES,
    DEFAULT_CONCURRENCY,
    JOB_QUEUE_ROUTING,
    QUEUE_COVER,
    QUEUE_INGEST,
    QUEUE_INTERACTIVE,
    QUEUE_RENDER,
)


def test_all_queues_contains_four_entries():
    assert len(ALL_QUEUES) == 4
    assert QUEUE_INTERACTIVE in ALL_QUEUES
    assert QUEUE_INGEST in ALL_QUEUES
    assert QUEUE_COVER in ALL_QUEUES
    assert QUEUE_RENDER in ALL_QUEUES


def test_cover_thumbnail_job_does_not_share_a_queue_with_import_or_hash_jobs():
    """A SAQ Redis queue is FIFO. While the cover job shared `ingest`, a bulk
    library import put every later cover behind the import and hash jobs of
    all the other galleries (2026-10-09: median 157 s, up to 402 s queued)."""
    cover_queue = JOB_QUEUE_ROUTING["cover_thumbnail_job"]

    assert cover_queue == QUEUE_COVER
    sharing = [job for job, queue in JOB_QUEUE_ROUTING.items() if queue == cover_queue]
    assert sharing == ["cover_thumbnail_job"]


def test_render_jobs_route_to_render_queue():
    assert JOB_QUEUE_ROUTING["thumbnail_job"] == QUEUE_RENDER
    assert JOB_QUEUE_ROUTING["thumbhash_backfill_job"] == QUEUE_RENDER


def test_ingest_jobs_route_to_ingest_queue():
    assert JOB_QUEUE_ROUTING["local_import_job"] == QUEUE_INGEST
    assert JOB_QUEUE_ROUTING["link_hash_job"] == QUEUE_INGEST
    assert JOB_QUEUE_ROUTING["auto_discover_job"] == QUEUE_INGEST


def test_watcher_lifecycle_jobs_route_to_interactive_queue():
    assert JOB_QUEUE_ROUTING["move_library_path_job"] == QUEUE_INTERACTIVE
    assert JOB_QUEUE_ROUTING["reconcile_library_path_job"] == QUEUE_INTERACTIVE


def test_unlisted_jobs_are_not_in_routing_map():
    """Jobs not listed default to interactive at call sites — they must be absent."""
    interactive_jobs = [
        "download_job",
        "import_job",
        "batch_import_job",
        "tag_job",
        "dedup_scan_job",
        "rescan_gallery_job",
        "reconciliation_job",
        "ehtag_sync_job",
        "disk_monitor_job",
    ]
    for job in interactive_jobs:
        assert job not in JOB_QUEUE_ROUTING, f"{job} should not be in routing map"


def test_default_concurrency_has_all_queues():
    for q in ALL_QUEUES:
        assert q in DEFAULT_CONCURRENCY
        assert DEFAULT_CONCURRENCY[q] > 0
