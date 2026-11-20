"""Redis Pub/Sub helpers: subscription handle and a reconnecting listener loop."""

import asyncio
from contextlib import suppress

from core.redis_client import get_redis


def get_pubsub():
    """Return a new PubSub object for subscribing to channels."""
    return get_redis().pubsub()


_PUBSUB_RETRY_START = 1.0
_PUBSUB_RETRY_MAX = 30.0


async def pubsub_listen_forever(
    channel: str,
    on_message,
    *,
    on_subscribe=None,
    name: str,
) -> None:
    """Subscribe to `channel` and dispatch messages until the task is cancelled.

    A Redis restart drops every subscription and redis-py does not resubscribe on
    its own, so a listener that treats a connection error as terminal goes deaf
    for the rest of the process lifetime without surfacing anything afterwards.
    This retries with exponential backoff instead.

    `on_subscribe` runs after every successful (re)subscribe, including the first.
    Messages published while the connection was down are lost with no way to
    replay them, so callers use this hook to resynchronise whatever state the
    channel keeps up to date.
    """
    import logging

    logger = logging.getLogger(__name__)
    backoff = _PUBSUB_RETRY_START

    while True:
        pubsub = None
        try:
            pubsub = get_pubsub()
            await pubsub.subscribe(channel)
            backoff = _PUBSUB_RETRY_START
            if on_subscribe is not None:
                await on_subscribe()
            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                try:
                    await on_message(message["data"])
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    # A single bad payload must not cost us the subscription.
                    logger.warning("[%s] Failed to process message: %s", name, exc)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "[%s] Pub/Sub connection lost (%s); resubscribing in %.2fs",
                name,
                exc,
                backoff,
            )
        finally:
            if pubsub is not None:
                with suppress(Exception):
                    await pubsub.unsubscribe(channel)
                with suppress(Exception):
                    await pubsub.aclose()

        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, _PUBSUB_RETRY_MAX)
