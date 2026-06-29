"""Regression tests for worker heap reclamation (worker/memory.py).

Heavy batch jobs (dedup pHash scan, bulk import, thumbnailing) allocate and free
hundreds of MB transiently. CPython frees the Python objects but glibc keeps the
freed arenas, so the worker RSS ratchets up in plateaus and is only reclaimed on
restart — eventually hitting the 2 GB cap (and, before the cap, the whole host).
``trim_memory`` forces a GC sweep + ``malloc_trim`` to return that heap to the OS,
gated to fire only after memory-heavy jobs.
"""

from unittest.mock import MagicMock


def test_trim_memory_runs_gc_then_malloc_trim(monkeypatch):
    from worker import memory as m

    calls = []
    monkeypatch.setattr(m.gc, "collect", lambda *a, **k: calls.append("gc") or 0)
    monkeypatch.setattr(m, "_malloc_trim", lambda: calls.append("trim"))

    m.trim_memory()

    assert calls == ["gc", "trim"]


def test_malloc_trim_calls_libc_when_available(monkeypatch):
    from worker import memory as m

    fake_libc = MagicMock()
    monkeypatch.setattr(m, "_load_libc", lambda: fake_libc)

    m._malloc_trim()

    fake_libc.malloc_trim.assert_called_once_with(0)


def test_malloc_trim_is_noop_without_glibc(monkeypatch):
    """On musl / when libc cannot be loaded, trimming must not raise."""
    from worker import memory as m

    monkeypatch.setattr(m, "_load_libc", lambda: None)

    m._malloc_trim()  # must not raise


async def test_after_process_trims_after_heavy_job(monkeypatch):
    from worker import memory as m

    called = []
    monkeypatch.setattr(m, "trim_memory", lambda: called.append(True))
    job = MagicMock()
    job.function = "dedup_scan_job"

    await m.after_process_hook({"job": job})

    assert called == [True]


async def test_after_process_skips_light_job(monkeypatch):
    from worker import memory as m

    called = []
    monkeypatch.setattr(m, "trim_memory", lambda: called.append(True))
    job = MagicMock()
    job.function = "adaptive_persist_job"

    await m.after_process_hook({"job": job})

    assert called == []


async def test_after_process_handles_missing_job(monkeypatch):
    from worker import memory as m

    called = []
    monkeypatch.setattr(m, "trim_memory", lambda: called.append(True))

    await m.after_process_hook({})  # must not raise

    assert called == []


# ---------------------------------------------------------------------------
# Container memory reading (cgroup v2)
# ---------------------------------------------------------------------------


def test_read_container_memory_parses_cgroup_files(tmp_path):
    from worker import memory as m

    (tmp_path / "memory.current").write_text("104857600\n")
    (tmp_path / "memory.max").write_text("2147483648\n")

    assert m.read_container_memory(str(tmp_path / "memory.current"), str(tmp_path / "memory.max")) == (
        104857600,
        2147483648,
    )


def test_read_container_memory_returns_none_when_limit_is_unbounded(tmp_path):
    """cgroup reports ``max`` when no memory limit is set — percentage is meaningless."""
    from worker import memory as m

    (tmp_path / "memory.current").write_text("100\n")
    (tmp_path / "memory.max").write_text("max\n")

    assert m.read_container_memory(str(tmp_path / "memory.current"), str(tmp_path / "memory.max")) is None


def test_read_container_memory_returns_none_when_files_missing(tmp_path):
    from worker import memory as m

    assert m.read_container_memory(str(tmp_path / "nope"), str(tmp_path / "nope2")) is None


# ---------------------------------------------------------------------------
# memory_monitor_job — log/event alert when over threshold
# ---------------------------------------------------------------------------


async def test_memory_monitor_job_warns_when_usage_exceeds_threshold(monkeypatch):
    from unittest.mock import AsyncMock

    import worker
    from core import events

    # 90% of a 2 GB limit, default threshold 85% → must alert
    monkeypatch.setattr("worker.memory.read_container_memory", lambda: (int(2_000_000_000 * 0.90), 2_000_000_000))
    emit = AsyncMock()
    monkeypatch.setattr(events, "emit_safe", emit)

    result = await worker.memory_monitor_job({})

    assert result["status"] == "high"
    emit.assert_awaited_once()
    assert emit.await_args.args[0] == events.EventType.SYSTEM_MEMORY_HIGH


async def test_memory_monitor_job_silent_when_usage_below_threshold(monkeypatch):
    from unittest.mock import AsyncMock

    import worker
    from core import events

    monkeypatch.setattr("worker.memory.read_container_memory", lambda: (int(2_000_000_000 * 0.50), 2_000_000_000))
    emit = AsyncMock()
    monkeypatch.setattr(events, "emit_safe", emit)

    result = await worker.memory_monitor_job({})

    assert result["status"] == "ok"
    emit.assert_not_awaited()


async def test_memory_monitor_job_unknown_when_cgroup_unavailable(monkeypatch):
    import worker

    monkeypatch.setattr("worker.memory.read_container_memory", lambda: None)

    result = await worker.memory_monitor_job({})

    assert result["status"] == "unknown"


# ---------------------------------------------------------------------------
# Host memory reading (/proc/meminfo)
# ---------------------------------------------------------------------------


def test_read_host_memory_parses_meminfo(tmp_path):
    from worker import memory as m

    p = tmp_path / "meminfo"
    p.write_text("MemTotal:       8000000 kB\nMemFree:         100000 kB\nMemAvailable:   3000000 kB\n")

    used, total = m.read_host_memory(str(p))

    assert total == 8000000 * 1024
    assert used == (8000000 - 3000000) * 1024


def test_read_host_memory_returns_none_when_missing(tmp_path):
    from worker import memory as m

    assert m.read_host_memory(str(tmp_path / "nope")) is None


# ---------------------------------------------------------------------------
# DEBUG history recording — hardcoded flag, default off
# ---------------------------------------------------------------------------


async def test_memory_history_flag_defaults_off():
    """The DEBUG history switch must ship disabled so production never writes."""
    from worker import memory as m

    assert m.MEMORY_HISTORY_ENABLED is False


async def test_memory_monitor_job_records_worker_and_host_when_flag_on(monkeypatch):
    from unittest.mock import AsyncMock

    import worker
    from core import events
    from worker import memory as m

    monkeypatch.setattr("worker.memory.read_container_memory", lambda: (int(2_000_000_000 * 0.50), 2_000_000_000))
    monkeypatch.setattr("worker.memory.read_host_memory", lambda: (int(8_000_000_000 * 0.50), 8_000_000_000))
    monkeypatch.setattr(events, "emit_safe", AsyncMock())
    monkeypatch.setattr(m, "MEMORY_HISTORY_ENABLED", True)
    persist = AsyncMock()
    monkeypatch.setattr(m, "persist_memory_history", persist)

    await worker.memory_monitor_job({})

    persist.assert_awaited_once()
    samples = persist.await_args.args[0]
    assert {s[0] for s in samples} == {"worker", "host"}


async def test_memory_monitor_job_skips_history_when_flag_off(monkeypatch):
    from unittest.mock import AsyncMock

    import worker
    from core import events
    from worker import memory as m

    monkeypatch.setattr("worker.memory.read_container_memory", lambda: (int(2_000_000_000 * 0.50), 2_000_000_000))
    monkeypatch.setattr(events, "emit_safe", AsyncMock())
    monkeypatch.setattr(m, "MEMORY_HISTORY_ENABLED", False)
    persist = AsyncMock()
    monkeypatch.setattr(m, "persist_memory_history", persist)

    await worker.memory_monitor_job({})

    persist.assert_not_awaited()
