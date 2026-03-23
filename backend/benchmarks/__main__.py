"""Allow running as `python -m benchmarks`."""
import asyncio

from benchmarks.run import main

asyncio.run(main())
