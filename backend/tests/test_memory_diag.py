"""
Regression coverage for container memory readings and the high-memory alert.

Incident 2026-08-13: the worker was OOM-killed at 02:02:56 by PIL decode
buffers, and the 5-minute monitor said nothing. Two minutes later, on a
worker that had been up for 120 seconds, it logged
``HIGH: 2048 MB / 2048 MB (100.0%)``.

Both failures come from the same choice of metric. ``memory.current`` in
cgroup v2 includes page cache, and an import reading hundreds of image files
fills that instantly. Page cache is reclaimed under pressure rather than
triggering a kill, so it inflates the reading without representing risk:
measured on the live worker, ``memory.current`` was 385.7 MB of which only
116.2 MB was ``anon`` — a 3.3x overstatement.

So the alert is driven by ``anon`` (unreclaimable, what actually reaches
``memory.max``), and ``memory.peak`` — a kernel-maintained high-water mark
that needs no sampling — is reported so sub-second spikes stay visible.
"""

from pathlib import Path
from unittest.mock import AsyncMock

MEMORY_STAT = """anon 121634816
file 275640320
kernel_stack 131072
pagetables 2260992
sock 0
shmem 0
file_mapped 30408704
slab 6291456
"""


def _write_cgroup(
    tmp_path: Path,
    *,
    current: str = "385654784",
    limit: str = "2147483648",
    peak: str | None = "434384896",
    stat: str = MEMORY_STAT,
) -> dict[str, str]:
    paths = {}
    for name, content in (
        ("memory.current", current),
        ("memory.max", limit),
        ("memory.stat", stat),
    ):
        p = tmp_path / name
        p.write_text(content)
        paths[name] = str(p)
    peak_path = tmp_path / "memory.peak"
    if peak is not None:
        peak_path.write_text(peak)
    paths["memory.peak"] = str(peak_path)
    return paths


class TestReadContainerMemoryDetail:
    def test_separates_anon_from_reclaimable_page_cache(self, tmp_path: Path) -> None:
        """The whole point: `current` counts page cache, `anon` does not."""
        from services.memory_diag import read_container_memory_detail

        p = _write_cgroup(tmp_path)
        detail = read_container_memory_detail(
            current_path=p["memory.current"],
            max_path=p["memory.max"],
            stat_path=p["memory.stat"],
            peak_path=p["memory.peak"],
        )

        assert detail is not None
        assert detail.current == 385654784
        assert detail.anon == 121634816
        assert detail.limit == 2147483648
        # current/limit would read 18.0%; anon/limit is the honest 5.7%.
        assert round(detail.current / detail.limit * 100, 1) == 18.0
        assert round(detail.anon / detail.limit * 100, 1) == 5.7

    def test_reports_kernel_high_water_mark(self, tmp_path: Path) -> None:
        """memory.peak captures spikes between samples; memory.current cannot."""
        from services.memory_diag import read_container_memory_detail

        p = _write_cgroup(tmp_path, current="100000000", peak="1900000000")
        detail = read_container_memory_detail(
            current_path=p["memory.current"],
            max_path=p["memory.max"],
            stat_path=p["memory.stat"],
            peak_path=p["memory.peak"],
        )

        assert detail is not None
        assert detail.peak == 1900000000
        assert detail.current == 100000000, "a spike must not be inferred from current"

    def test_missing_peak_file_degrades_instead_of_failing(self, tmp_path: Path) -> None:
        """memory.peak needs a recent kernel; its absence must not lose the rest."""
        from services.memory_diag import read_container_memory_detail

        p = _write_cgroup(tmp_path, peak=None)
        detail = read_container_memory_detail(
            current_path=p["memory.current"],
            max_path=p["memory.max"],
            stat_path=p["memory.stat"],
            peak_path=p["memory.peak"],
        )

        assert detail is not None
        assert detail.peak is None
        assert detail.anon == 121634816

    def test_missing_stat_file_falls_back_to_current(self, tmp_path: Path) -> None:
        """Without memory.stat there is no anon figure; do not invent one."""
        from services.memory_diag import read_container_memory_detail

        p = _write_cgroup(tmp_path)
        detail = read_container_memory_detail(
            current_path=p["memory.current"],
            max_path=p["memory.max"],
            stat_path=str(tmp_path / "absent.stat"),
            peak_path=p["memory.peak"],
        )

        assert detail is not None
        assert detail.anon == detail.current, "fall back to the pessimistic figure"

    def test_returns_none_when_no_limit_is_set(self, tmp_path: Path) -> None:
        """An unlimited cgroup makes every percentage meaningless."""
        from services.memory_diag import read_container_memory_detail

        p = _write_cgroup(tmp_path, limit="max")
        assert (
            read_container_memory_detail(
                current_path=p["memory.current"],
                max_path=p["memory.max"],
                stat_path=p["memory.stat"],
                peak_path=p["memory.peak"],
            )
            is None
        )

    def test_legacy_reader_still_returns_current_and_limit(self, tmp_path: Path) -> None:
        """worker/memory.py re-exports this; keep its contract intact."""
        from services.memory_diag import read_container_memory

        p = _write_cgroup(tmp_path)
        assert read_container_memory(p["memory.current"], p["memory.max"]) == (385654784, 2147483648)


class TestMemoryAlertUsesAnon:
    """The 2026-08-13 false alarm, and the real spike it missed."""

    @staticmethod
    def _quiet_redis(monkeypatch):
        monkeypatch.setattr(
            "worker.redis_memory.sample_redis_memory",
            AsyncMock(
                return_value={
                    "used_bytes": 10,
                    "limit_bytes": 100,
                    "pct": 10.0,
                    "policy": "noeviction",
                    "evicted_keys": 0,
                }
            ),
        )

    async def test_page_cache_at_the_limit_does_not_alert(self, monkeypatch):
        """A worker 2 minutes old reading image files hits 100% of `current`.

        That is reclaimable cache, not OOM risk, and alerting on it is what
        produced the misleading `HIGH: 2048 MB / 2048 MB` line on 2026-08-13.
        """
        import worker
        from core import events
        from services.memory_diag import ContainerMemory

        limit = 2048 * 1024 * 1024
        monkeypatch.setattr(
            "worker.memory.read_container_memory_detail",
            lambda: ContainerMemory(current=limit, anon=180 * 1024 * 1024, peak=limit, limit=limit),
        )
        self._quiet_redis(monkeypatch)
        emit = AsyncMock()
        monkeypatch.setattr(events, "emit_safe", emit)

        result = await worker.memory_monitor_job({"redis": AsyncMock()})

        assert result["status"] == "ok"
        emit.assert_not_awaited()

    async def test_anon_above_threshold_alerts(self, monkeypatch):
        """Unreclaimable growth is the condition that actually precedes a kill."""
        import worker
        from core import events
        from services.memory_diag import ContainerMemory

        limit = 2048 * 1024 * 1024
        monkeypatch.setattr(
            "worker.memory.read_container_memory_detail",
            lambda: ContainerMemory(current=limit, anon=1900 * 1024 * 1024, peak=limit, limit=limit),
        )
        self._quiet_redis(monkeypatch)
        emit = AsyncMock()
        monkeypatch.setattr(events, "emit_safe", emit)

        result = await worker.memory_monitor_job({"redis": AsyncMock()})

        assert result["status"] == "high"
        emit.assert_awaited_once()
        kwargs = emit.await_args.kwargs
        assert kwargs["anon_mb"] == 1900.0
        assert kwargs["peak_mb"] == 2048.0, "the spike must survive into the alert"
