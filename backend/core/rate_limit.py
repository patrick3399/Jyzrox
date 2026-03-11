"""Redis-based rate limiter using sliding window counter."""

import ipaddress
import logging
from functools import lru_cache

from fastapi import HTTPException, Request, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

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
        await redis.expire(redis_key, window + 1)

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


# ---------------------------------------------------------------------------
# Global rate-limiting middleware
# ---------------------------------------------------------------------------

# Global per-IP limits (all methods)
_GLOBAL_RATE_LIMIT = 600
_GLOBAL_RATE_WINDOW = 60  # seconds

# Stricter limit for mutating methods
_WRITE_RATE_LIMIT = 120
_WRITE_RATE_WINDOW = 60  # seconds

# Paths that carry their own stricter per-endpoint limits — skip global check
_SKIP_GLOBAL: frozenset[str] = frozenset({
    "/api/auth/login",
    "/api/auth/setup",
    "/api/auth/check",
})
_SKIP_GLOBAL_PREFIXES: tuple[str, ...] = (
    "/api/external/v1/",  # has its own per-token limiter
)


_PRIVATE_NETWORKS: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),   # covers 172.16–172.31
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
)


def _is_private(ip_str: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return any(addr in net for net in _PRIVATE_NETWORKS)


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not settings.rate_limit_enabled:
            return await call_next(request)

        path = request.url.path

        # Skip health check — no need to count liveness probes
        if path == "/api/health":
            return await call_next(request)

        # Skip paths that have their own rate limiting
        if path in _SKIP_GLOBAL or path.startswith(_SKIP_GLOBAL_PREFIXES):
            return await call_next(request)

        client_ip = get_client_ip(request)

        # Bypass rate limiting for private/LAN clients
        if _is_private(client_ip):
            return await call_next(request)
        redis = get_redis()

        # 1. Global per-IP limit (all methods)
        global_key = f"ratelimit:global:{client_ip}"
        count = await redis.incr(global_key)
        if count == 1:
            await redis.expire(global_key, _GLOBAL_RATE_WINDOW)
        if count > _GLOBAL_RATE_LIMIT:
            ttl = await redis.ttl(global_key)
            return JSONResponse(
                status_code=429,
                content={"detail": f"Too many requests. Try again in {ttl}s."},
                headers={"Retry-After": str(ttl)},
            )

        # 2. Stricter limit for mutating methods
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            write_key = f"ratelimit:write:{client_ip}"
            wcount = await redis.incr(write_key)
            if wcount == 1:
                await redis.expire(write_key, _WRITE_RATE_WINDOW)
            if wcount > _WRITE_RATE_LIMIT:
                ttl = await redis.ttl(write_key)
                return JSONResponse(
                    status_code=429,
                    content={"detail": f"Too many requests. Try again in {ttl}s."},
                    headers={"Retry-After": str(ttl)},
                )

        return await call_next(request)
