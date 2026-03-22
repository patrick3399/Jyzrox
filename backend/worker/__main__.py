"""Entry point for `python -m worker`."""

import asyncio

from worker import build_worker

if __name__ == "__main__":
    worker = build_worker()
    asyncio.run(worker.start())
