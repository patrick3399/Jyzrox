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
