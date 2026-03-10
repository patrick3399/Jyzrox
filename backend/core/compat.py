"""Python version compatibility shims."""

import asyncio
import sys


def patch_asyncio_for_314():
    """Python 3.14 removed implicit event loop creation in get_event_loop().

    This patch restores the pre-3.14 behavior so that arq 0.27.0 and our own
    code that calls get_event_loop() outside of a running loop keep working.

    Remove this once arq releases a version with native 3.14 support.
    """
    if sys.version_info >= (3, 14):
        _original = asyncio.get_event_loop

        def _get_event_loop():
            try:
                return _original()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                return loop

        asyncio.get_event_loop = _get_event_loop
