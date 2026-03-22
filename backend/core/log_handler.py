"""Redis-backed logging handler for streaming logs to the admin UI."""

import asyncio
import json
import logging
import traceback
from datetime import UTC, datetime

LOG_LEVEL_KEYS: dict[str, str] = {
    "api": "log_level:api",
    "worker": "log_level:worker",
}

VALID_LEVELS: set[str] = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}

LOG_LEVEL_CHANNEL = "log_level:changed"

_trim_counter: int = 0
_TRIM_INTERVAL = 100


class RedisLogHandler(logging.Handler):
    """Async-aware logging handler that pushes log entries to Redis."""

    LIST_KEY = "system_logs"

    def __init__(self, source: str, max_entries: int = 2_000) -> None:
        super().__init__()
        self.source = source
        self.max_entries = max_entries

    def emit(self, record: logging.LogRecord) -> None:
        try:
            tb = None
            if record.exc_info:
                tb = traceback.format_exception(*record.exc_info)
                tb = "".join(tb)

            payload = json.dumps({
                "level": record.levelname,
                "source": self.source,
                "logger": record.name,
                "message": self.format(record),
                "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
                **({"traceback": tb} if tb else {}),
            })

            try:
                loop = asyncio.get_running_loop()
                if loop.is_running():
                    loop.create_task(self._async_emit(payload))
            except RuntimeError:
                # No running event loop — silently drop
                pass
        except Exception:
            # Never let the log handler raise
            pass

    async def _async_emit(self, payload: str) -> None:
        global _trim_counter
        try:
            from core.redis_client import get_redis
            r = get_redis()
            pipe = r.pipeline(transaction=False)
            pipe.lpush(self.LIST_KEY, payload)
            pipe.publish("logs:stream", payload)
            _trim_counter += 1
            if _trim_counter >= _TRIM_INTERVAL:
                pipe.ltrim(self.LIST_KEY, 0, self.max_entries - 1)
                _trim_counter = 0
            await pipe.execute()
        except Exception:
            pass


def install_log_handler(source: str, extra_loggers: list[str] | None = None) -> None:
    """Create a RedisLogHandler, attach a simple formatter, and add to root logger."""
    handler = RedisLogHandler(source=source)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logging.getLogger().addHandler(handler)
    for name in (extra_loggers or []):
        logging.getLogger(name).addHandler(handler)


async def read_log_level(source: str) -> str:
    """Read the persisted log level for *source* from Redis.

    Returns the level string (e.g. 'DEBUG') or 'INFO' if not set / invalid.
    """
    try:
        from core.redis_client import get_redis
        r = get_redis()
        key = LOG_LEVEL_KEYS.get(source, f"log_level:{source}")
        raw = await r.get(key)
        if raw is not None:
            level = raw.decode() if isinstance(raw, bytes) else str(raw)
            level = level.upper()
            if level in VALID_LEVELS:
                return level
    except Exception:
        pass
    return "INFO"


async def apply_log_level_from_redis(source: str) -> str:
    """Read log level from Redis and apply it to the root logger."""
    level = await read_log_level(source)
    logging.getLogger().setLevel(level)
    return level


async def set_log_level(source: str, level: str) -> None:
    """Persist log level to Redis and publish a change notification."""
    from core.redis_client import get_redis
    r = get_redis()
    key = LOG_LEVEL_KEYS.get(source, f"log_level:{source}")
    await r.set(key, level)
    await r.publish(LOG_LEVEL_CHANNEL, json.dumps({"source": source, "level": level}))
