"""CSRF protection via the double-submit cookie pattern."""

import hmac

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

_EXEMPT_PATHS = {
    "/api/auth/login",
    "/api/auth/logout",
    "/api/auth/setup",
    "/api/auth/check",
    "/api/auth/needs-setup",
    "/api/health",
    "/api/download/quick",
}

_EXEMPT_PREFIXES = (
    "/api/external/v1/",
    "/opds/",
    "/api/ws/",
)


class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method in _SAFE_METHODS:
            return await call_next(request)

        path = request.url.path
        if path in _EXEMPT_PATHS or path.startswith(_EXEMPT_PREFIXES):
            return await call_next(request)

        # Check runtime toggle
        try:
            from core.redis_client import get_redis
            from core.config import settings
            val = await get_redis().get("setting:csrf_enabled")
            if val is not None:
                enabled = val == b"1"
            else:
                enabled = settings.csrf_enabled
            if not enabled:
                return await call_next(request)
        except Exception:
            pass  # If Redis is unavailable, keep CSRF enabled (fail-closed)

        cookie_token = request.cookies.get("csrf_token")
        header_token = request.headers.get("x-csrf-token")

        if not cookie_token or not header_token or not hmac.compare_digest(cookie_token, header_token):
            return JSONResponse(
                status_code=403,
                content={"detail": "CSRF token missing or invalid"},
            )

        return await call_next(request)
