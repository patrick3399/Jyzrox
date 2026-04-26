"""Entry point for `python -m worker`."""

import asyncio

from worker import build_workers


async def _main() -> None:
    workers = build_workers()
    await asyncio.gather(*[w.start() for w in workers])


if __name__ == "__main__":
    asyncio.run(_main())
