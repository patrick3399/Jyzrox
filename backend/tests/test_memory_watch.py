"""Tests for the api memory self-sampling watch (services/memory_watch.py, STAB-011).

The api container's memory floor creeps up over weeks and only a restart
reclaims it; the watch task gives each api process an RSS-over-uptime trail in
the logs plus optional DEBUG history rows, so the creep can be quantified and
attributed. These tests pin the sampling contract: RSS parsing, per-pid history
labelling, threshold alerting, and the worker re-exports that keep the
documented MEMORY_HISTORY_ENABLED debug switch stable.
"""

import os
from unittest.mock import AsyncMock

import pytest

from services import memory_diag, memory_watch

# ---------------------------------------------------------------------------
# read_self_rss
# ---------------------------------------------------------------------------


def test_read_self_rss_parses_vmrss_kb(tmp_path):
    status = tmp_path / "status"
    status.write_text("Name:\tpython\nVmPeak:\t  300000 kB\nVmRSS:\t  181920 kB\nThreads:\t12\n")
    assert memory_watch.read_self_rss(str(status)) == 181920 * 1024


def test_read_self_rss_missing_file_returns_none(tmp_path):
    assert memory_watch.read_self_rss(str(tmp_path / "nope")) is None


def test_read_self_rss_no_vmrss_line_returns_none(tmp_path):
    status = tmp_path / "status"
    status.write_text("Name:\tpython\nThreads:\t12\n")
    assert memory_watch.read_self_rss(str(status)) is None


# ---------------------------------------------------------------------------
# sample_once
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sample_once_reports_ok_below_threshold(monkeypatch):
    monkeypatch.setattr(memory_watch, "read_self_rss", lambda *a: 150 * 1024 * 1024)
    monkeypatch.setattr(memory_diag, "read_container_memory", lambda *a: (300 * 1024 * 1024, 2048 * 1024 * 1024))
    emit = AsyncMock()
    monkeypatch.setattr("core.events.emit_safe", emit)

    result = await memory_watch.sample_once()

    assert result["status"] == "ok"
    assert result["rss_mb"] == 150.0
    emit.assert_not_awaited()


@pytest.mark.asyncio
async def test_sample_once_alerts_when_cgroup_usage_exceeds_threshold(monkeypatch):
    monkeypatch.setattr(memory_watch, "read_self_rss", lambda *a: 900 * 1024 * 1024)
    monkeypatch.setattr(memory_diag, "read_container_memory", lambda *a: (1900 * 1024 * 1024, 2048 * 1024 * 1024))
    emit = AsyncMock()
    monkeypatch.setattr("core.events.emit_safe", emit)

    result = await memory_watch.sample_once()

    assert result["status"] == "high"
    emit.assert_awaited_once()
    kwargs = emit.await_args.kwargs
    assert kwargs["component"] == "api"
    assert kwargs["pct"] >= 85.0


@pytest.mark.asyncio
async def test_sample_once_survives_missing_cgroup(monkeypatch):
    """Dev machines without cgroup v2 must still get the RSS log line."""
    monkeypatch.setattr(memory_watch, "read_self_rss", lambda *a: 150 * 1024 * 1024)
    monkeypatch.setattr(memory_diag, "read_container_memory", lambda *a: None)

    result = await memory_watch.sample_once()

    assert result == {"status": "ok", "pid": os.getpid(), "rss_mb": 150.0}


@pytest.mark.asyncio
async def test_sample_once_records_per_pid_history_when_enabled(monkeypatch):
    monkeypatch.setattr(memory_watch, "read_self_rss", lambda *a: 150 * 1024 * 1024)
    monkeypatch.setattr(memory_diag, "read_container_memory", lambda *a: (300 * 1024 * 1024, 2048 * 1024 * 1024))
    monkeypatch.setattr(memory_diag, "MEMORY_HISTORY_ENABLED", True)
    persist = AsyncMock()
    monkeypatch.setattr(memory_diag, "persist_memory_history", persist)

    await memory_watch.sample_once()

    persist.assert_awaited_once()
    samples = persist.await_args.args[0]
    assert samples == [(f"api:{os.getpid()}", 150.0, 2048.0, 7.3)]


@pytest.mark.asyncio
async def test_sample_once_skips_history_when_disabled(monkeypatch):
    monkeypatch.setattr(memory_watch, "read_self_rss", lambda *a: 150 * 1024 * 1024)
    monkeypatch.setattr(memory_diag, "read_container_memory", lambda *a: (300 * 1024 * 1024, 2048 * 1024 * 1024))
    monkeypatch.setattr(memory_diag, "MEMORY_HISTORY_ENABLED", False)
    persist = AsyncMock()
    monkeypatch.setattr(memory_diag, "persist_memory_history", persist)

    await memory_watch.sample_once()

    persist.assert_not_awaited()


# ---------------------------------------------------------------------------
# worker re-exports — moving the helpers to services/memory_diag.py must not
# break the documented `worker.memory` debug-switch surface
# ---------------------------------------------------------------------------


def test_worker_memory_reexports_shared_helpers():
    from worker import memory as m

    assert m.read_container_memory is memory_diag.read_container_memory
    assert m.read_host_memory is memory_diag.read_host_memory
    assert m.persist_memory_history is memory_diag.persist_memory_history
    assert m.MEMORY_HISTORY_ENABLED is memory_diag.MEMORY_HISTORY_ENABLED
