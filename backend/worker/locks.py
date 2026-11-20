"""Renewable Redis lock helpers for the worker package."""


# ── Renewable Lock ────────────────────────────────────────────────────

LOCK_RELEASE_LUA = "if redis.call('get',KEYS[1])==ARGV[1] then return redis.call('del',KEYS[1]) else return 0 end"
LOCK_RENEW_LUA = (
    "if redis.call('get',KEYS[1])==ARGV[1] then return redis.call('expire',KEYS[1],ARGV[2]) else return 0 end"
)


async def acquire_lock(redis, key: str, ttl: int = 300) -> str | None:
    """Acquire a distributed lock with a unique value. Returns lock_value or None."""
    import uuid as _uuid

    lock_value = str(_uuid.uuid4())
    acquired = await redis.set(key, lock_value, nx=True, ex=ttl)
    if acquired:
        return lock_value
    return None


async def release_lock(redis, key: str, lock_value: str) -> bool:
    """Release a lock only if we still own it (compare-and-delete via Lua)."""
    result = await redis.eval(LOCK_RELEASE_LUA, 1, key, lock_value)
    return result == 1


async def renew_lock(redis, key: str, lock_value: str, ttl: int) -> bool:
    """Extend a lock's TTL only if we still own it (compare-and-expire).

    Lets a holder outlive its initial TTL while it is demonstrably still
    working, without ever resetting the expiry on a lock somebody else now
    owns. Returns False once the lock is gone or has changed hands, which the
    caller should treat as having lost mutual exclusion.
    """
    result = await redis.eval(LOCK_RENEW_LUA, 1, key, lock_value, ttl)
    return result == 1
