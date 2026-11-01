"""Regression coverage for the worker's SIGTERM handling.

SAQ's ``Worker.start()`` installs ``loop.add_signal_handler(SIGTERM, self.event.set)``.
``worker.__main__`` runs three Workers (interactive/ingest/render) on ONE event
loop, and asyncio keeps a single handler per signal, so the last Worker to
start (render) replaced the other two. ``docker stop`` therefore stopped only
render; the process kept running until the 55s grace period expired and Docker
SIGKILLed it. The interactive Worker's ``shutdown()`` — which clears the
``worker:run_marker`` — never ran, so every restart logged a false
``[liveness] previous worker run ended without shutting down`` ERROR.

The fakes below reproduce SAQ's ``start()``/``stop()`` contract (same
``SIGNALS`` attribute, same handler registration, same CancelledError/finally
structure, verified against saq 0.26.3 in the worker container).
"""

import asyncio
import os
import signal

import pytest

NAMES = ("interactive", "ingest", "render")


class _SaqLikeWorker:
    SIGNALS = [signal.SIGINT, signal.SIGTERM]

    def __init__(self, name: str, record: list[str]):
        self.name = name
        self.record = record
        self.started = asyncio.Event()

    async def start(self) -> None:
        try:
            self.event = asyncio.Event()
            loop = asyncio.get_running_loop()
            for signum in self.SIGNALS:
                loop.add_signal_handler(signum, self.event.set)
            self.started.set()
            await self.event.wait()
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()
            for signum in self.SIGNALS:
                loop.remove_signal_handler(signum)

    async def stop(self) -> None:
        self.record.append(f"{self.name}:shutdown")


@pytest.fixture
def workers_and_record(monkeypatch):
    import worker.__main__ as entry

    record: list[str] = []
    workers = tuple(_SaqLikeWorker(n, record) for n in NAMES)
    monkeypatch.setattr(entry, "build_workers", lambda: workers)
    return entry, workers, record


async def _signal_and_snapshot(entry, workers, record, sig: int) -> tuple[list[str], bool]:
    """Deliver ``sig`` to a running ``_main()``; return what shut down *because of the signal*.

    The snapshot is taken before cleanup: cancelling stragglers afterwards would
    run their stop() and mask exactly the workers the signal failed to stop.
    """
    loop = asyncio.get_running_loop()
    task = asyncio.create_task(entry._main())
    try:
        await asyncio.wait_for(asyncio.gather(*[w.started.wait() for w in workers]), timeout=2)
        os.kill(os.getpid(), sig)
        done, _ = await asyncio.wait({task}, timeout=2)
        return list(record), bool(done)
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        for s in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(s)


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT])
async def test_signal_runs_shutdown_for_all_three_workers_and_exits(workers_and_record, sig):
    entry, workers, record = workers_and_record

    shutdown_by_signal, exited = await _signal_and_snapshot(entry, workers, record, sig)

    assert sorted(shutdown_by_signal) == sorted(f"{n}:shutdown" for n in NAMES), (
        "the signal must stop every worker; the interactive one owns shutdown() and clears worker:run_marker"
    )
    assert exited, "the process must exit on the signal instead of idling until Docker's SIGKILL"


async def test_repeated_sigterm_does_not_interrupt_a_shutdown_in_progress(monkeypatch, workers_and_record):
    """A second SIGTERM (e.g. a retried `docker stop`) must not cancel a shutdown hook midway."""
    entry, workers, record = workers_and_record
    loop = asyncio.get_running_loop()
    gate = asyncio.Event()

    async def slow_stop():
        record.append("interactive:shutdown-begin")
        await gate.wait()
        record.append("interactive:shutdown-complete")

    workers[0].stop = slow_stop
    task = asyncio.create_task(entry._main())
    try:
        await asyncio.wait_for(asyncio.gather(*[w.started.wait() for w in workers]), timeout=2)
        os.kill(os.getpid(), signal.SIGTERM)
        await asyncio.sleep(0.1)
        os.kill(os.getpid(), signal.SIGTERM)
        await asyncio.sleep(0.1)
        gate.set()
        done, _ = await asyncio.wait({task}, timeout=2)
    finally:
        gate.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        for s in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(s)

    assert "interactive:shutdown-complete" in record
    assert done
