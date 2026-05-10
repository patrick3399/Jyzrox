"""Redis-backed boolean/integer setting reads and writes.

Extracted from routers/settings.py so workers and other services
can read feature toggles without importing a router module.
"""

from core.redis_client import get_redis


async def get_toggle(redis_key: str, default: bool) -> bool:
    """Read a boolean toggle from Redis, falling back to config default."""
    val = await get_redis().get(redis_key)
    if val is not None:
        return val == b"1"
    return default


async def set_toggle(redis_key: str, enabled: bool) -> bool:
    """Set a boolean toggle in Redis."""
    await get_redis().set(redis_key, "1" if enabled else "0")
    return enabled


async def get_int_setting(redis_key: str, default: int) -> int:
    """Read an integer setting from Redis, falling back to default."""
    val = await get_redis().get(redis_key)
    if val is not None:
        try:
            return int(val)
        except ValueError, TypeError:
            pass
    return default


async def get_float_setting(redis_key: str, default: float) -> float:
    """Read a float setting from Redis, falling back to default."""
    val = await get_redis().get(redis_key)
    if val is not None:
        try:
            return float(val)
        except ValueError, TypeError:
            pass
    return default
