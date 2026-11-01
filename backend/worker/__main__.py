"""Entry point for `python -m worker`."""

import asyncio
import signal

from worker import build_workers

_STOP_SIGNALS = (signal.SIGINT, signal.SIGTERM)


async def _main() -> None:
    workers = build_workers()

    # SAQ's Worker.start() registers its own SIGINT/SIGTERM handlers, but all
    # workers share this one event loop and asyncio keeps a single handler per
    # signal — the last worker to start (render) silently replaced the others.
    # `docker stop` then stopped only render, the process idled until the
    # grace period expired and was SIGKILLed, and the interactive worker's
    # shutdown() (which clears worker:run_marker) never ran. Own the signals here
    # and fan the stop out to every worker instead.
    for w in workers:
        w.SIGNALS = []

    tasks = [asyncio.create_task(w.start()) for w in workers]
    stopping = False

    def request_stop() -> None:
        nonlocal stopping
        if stopping:
            # A repeated signal (retried `docker stop`) must not interrupt shutdown hooks midway.
            return
        stopping = True
        for w, task in zip(workers, tasks, strict=True):
            event = getattr(w, "event", None)
            if event is not None:
                event.set()  # SAQ's own path: start() falls through to stop() and shutdown()
            else:
                task.cancel()  # still booting; start() handles CancelledError the same way

    loop = asyncio.get_running_loop()
    for signum in _STOP_SIGNALS:
        loop.add_signal_handler(signum, request_stop)
    try:
        await asyncio.gather(*tasks)
    finally:
        for signum in _STOP_SIGNALS:
            loop.remove_signal_handler(signum)


if __name__ == "__main__":
    asyncio.run(_main())
