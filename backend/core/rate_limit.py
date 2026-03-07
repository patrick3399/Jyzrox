"""Redis-based rate limiter using sliding window counter."""

import ipaddress
import logging
from functools import lru_cache

from fastapi import HTTPException, Request, status

from core.config import settings
from core.redis_client import get_redis

logger = logging.getLogger(__name__)


@lru_cache
def _trusted_networks() -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """Parse trusted_proxies setting into network objects (cached)."""
    nets = []
    for entry in settings.trusted_proxies.split(","):
        entry = entry.strip()
        if not entry:
            continue
        try:
            nets.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            logger.warning("Invalid trusted proxy entry: %s", entry)
    return nets


def _is_trusted(ip_str: str) -> bool:
    """Check if an IP address falls within any trusted proxy network."""
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return any(addr in net for net in _trusted_networks())


async def check_rate_limit(
    key: str,
    max_requests: int | None = None,
    window: int | None = None,
) -> None:
    """
    Raise 429 if the key has exceeded max_requests in the window.
    No-op if rate_limit_enabled is False in settings.
    """
    if not settings.rate_limit_enabled:
        return

    if max_requests is None:
        max_requests = settings.rate_limit_login
    if window is None:
        window = settings.rate_limit_window

    redis = get_redis()
    redis_key = f"ratelimit:{key}"

    count = await redis.incr(redis_key)
    if count == 1:
        await redis.expire(redis_key, window)

    if count > max_requests:
        ttl = await redis.ttl(redis_key)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many requests. Try again in {ttl}s.",
            headers={"Retry-After": str(ttl)},
        )


def get_client_ip(request: Request) -> str:
    """Extract client IP, respecting X-Forwarded-For only from trusted proxies."""
    peer_ip = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded and _is_trusted(peer_ip):
        return forwarded.split(",")[0].strip()
    return peer_ip
