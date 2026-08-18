"""Regression coverage for detecting a worker run that ended without shutting down.

Measured 2026-08-18 against the live stack: when the container's pid 1 is the
OOM victim, Docker recreates the cgroup on restart and `memory.events` comes
back reading `oom_kill 0`. Polling that counter therefore cannot see the very
kill that matters most — the one that took the whole worker down and stranded
four local imports on 2026-08-13.

The counter still catches the other half (a child killed while pid 1 survives,
verified to increment and persist), so the two mechanisms are complementary:
`memory.events` covers kills the worker survives, and this marker covers the
ones it does not.

The marker is deliberately inverted — its *presence* at startup means the
previous run never reached `shutdown()`. Losing the key can only produce a
missed report, never a false one.
"""

from unittest.mock import AsyncMock


class TestDetectUncleanExit:
    async def test_marker_left_behind_reports_the_previous_run(self):
        """pid 1 killed => shutdown() never ran => the marker is still there."""
        from worker.liveness import RUN_MARKER_KEY, detect_unclean_exit

        redis = AsyncMock()
        redis.get = AsyncMock(
            return_value=b'{"started_at": "2026-08-13T02:00:00+00:00", "last_anon_mb": 1904.2, "last_pct": 93.0}'
        )

        previous = await detect_unclean_exit(redis)

        assert previous is not None
        assert previous["last_anon_mb"] == 1904.2, "the last sample before the kill is the diagnostic"
        redis.delete.assert_awaited_once_with(RUN_MARKER_KEY)

    async def test_clean_shutdown_leaves_nothing_to_report(self):
        from worker.liveness import detect_unclean_exit

        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)

        assert await detect_unclean_exit(redis) is None

    async def test_unreadable_marker_is_not_reported_as_a_crash(self):
        """A corrupt value must not manufacture an incident out of nothing."""
        from worker.liveness import detect_unclean_exit

        redis = AsyncMock()
        redis.get = AsyncMock(return_value=b"not json")

        assert await detect_unclean_exit(redis) is None

    async def test_redis_failure_does_not_propagate_into_startup(self):
        """Startup must boot even when the marker cannot be read."""
        from worker.liveness import detect_unclean_exit

        redis = AsyncMock()
        redis.get = AsyncMock(side_effect=ConnectionError("redis down"))

        assert await detect_unclean_exit(redis) is None


class TestRunMarkerLifecycle:
    async def test_clear_marker_removes_it_so_the_next_boot_reads_clean(self):
        from worker.liveness import RUN_MARKER_KEY, clear_run_marker

        redis = AsyncMock()

        await clear_run_marker(redis)

        redis.delete.assert_awaited_once_with(RUN_MARKER_KEY)

    async def test_sample_update_preserves_the_marker_for_the_next_boot(self):
        """Each monitor tick refreshes the marker so a kill leaves fresh evidence."""
        import json

        from worker.liveness import RUN_MARKER_KEY, record_memory_sample

        redis = AsyncMock()

        await record_memory_sample(redis, anon_mb=1904.2, pct=93.0)

        redis.set.assert_awaited_once()
        key, raw = redis.set.await_args.args[0], redis.set.await_args.args[1]
        assert key == RUN_MARKER_KEY
        assert json.loads(raw)["last_anon_mb"] == 1904.2

    async def test_sample_update_survives_redis_being_down(self):
        from worker.liveness import record_memory_sample

        redis = AsyncMock()
        redis.set = AsyncMock(side_effect=ConnectionError("redis down"))

        await record_memory_sample(redis, anon_mb=1.0, pct=1.0)  # must not raise

    async def test_sample_update_keeps_the_run_start_time(self):
        """How long the run survived separates a decode spike from a slow leak.

        The 2026-08-13 kill hit a worker that had been up 120 seconds; a marker
        that only carries the latest sample cannot tell that from a run that
        lasted five days.
        """
        import json

        from worker.liveness import record_memory_sample, start_run_marker

        redis = AsyncMock()
        await start_run_marker(redis)
        started_at = json.loads(redis.set.await_args.args[1])["started_at"]

        await record_memory_sample(redis, anon_mb=1904.2, pct=93.0)

        marker = json.loads(redis.set.await_args.args[1])
        assert marker["started_at"] == started_at
        assert marker["last_anon_mb"] == 1904.2
