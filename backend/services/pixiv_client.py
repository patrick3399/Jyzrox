"""Pixiv API client wrapping pixivpy3."""

import asyncio
import hashlib
import logging
import secrets
import time
from collections.abc import Mapping
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
from pixivpy3 import AppPixivAPI

from core.client_identity import PIXIV_APP_REFERER, pixiv_app_headers
from core.config import settings
from core.redis_client import get_redis

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level shared HTTP client (singleton, lazy-created)
# ---------------------------------------------------------------------------
# Pixiv image downloads require Referer + User-Agent headers; they present the
# same app identity as the API calls. The shared client is reused across
# PixivClient instances to avoid creating a new connection pool per request.
#
# The Pixiv app path keeps Python's TLS: pixivpy3's cloudscraper session for
# API and OAuth calls, and this plain httpx client for pximg. Under an iOS app
# User-Agent that is a known mismatch, the same one gallery-dl's Pixiv app API
# has. It stays (decided 2026-10-25) because pixivpy3's cloudscraper session
# handles Cloudflare challenges on the OAuth endpoint, and no curl_cffi target
# is the Pixiv app's own iOS networking stack; services.browser_http is for
# browser requests only.

_shared_img_http: httpx.AsyncClient | None = None


def _get_shared_img_http() -> httpx.AsyncClient:
    global _shared_img_http
    if _shared_img_http is None or _shared_img_http.is_closed:
        _shared_img_http = httpx.AsyncClient(
            headers={**pixiv_app_headers(), "Referer": PIXIV_APP_REFERER},
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            timeout=settings.pixiv_request_timeout,
            follow_redirects=True,
        )
    return _shared_img_http


async def shutdown_shared_pixiv_clients() -> None:
    """Close shared httpx clients. Called from FastAPI lifespan shutdown."""
    global _shared_img_http
    if _shared_img_http and not _shared_img_http.is_closed:
        await _shared_img_http.aclose()


class _AppPixivAPI(AppPixivAPI):
    """AppPixivAPI that presents the Pixiv app identity from core.client_identity.

    pixivpy3 writes its own, older iOS identity into each call's headers, where
    ``additional_headers`` cannot override it. Every API, OAuth and download
    call goes through ``requests_call``, so the identity is applied there.
    """

    def requests_call(
        self,
        method: str,
        url: str,
        headers: Mapping[str, Any] | None = None,
        params: Any = None,
        data: Any = None,
        stream: bool = False,
    ) -> Any:
        identity = pixiv_app_headers()
        names = {name.lower() for name in identity}
        merged = {key: value for key, value in (headers or {}).items() if key.lower() not in names}
        merged.update(identity)
        return super().requests_call(method, url, merged, params, data, stream)


def new_app_api() -> AppPixivAPI:
    """Return a pixivpy3 client that presents the Pixiv app identity."""
    return _AppPixivAPI()


_TOKEN_KEY_PREFIX = "pixiv:access_token"
_LOCK_KEY_PREFIX = "pixiv:token_lock"
_TOKEN_TTL = 3500  # seconds — Pixiv tokens last 3600s; refresh before expiry
_LOCK_TIMEOUT = 10  # seconds


# Pixiv throttles by account and egress IP, so one shared cooldown covers every
# caller (downloads, subscriptions and browse pages): once a call is throttled,
# further requests only extend the ban.
_COOLDOWN_KEY = "pixiv:rate_limit:cooldown_until"
_RATE_LIMIT_COOLDOWN = 180  # seconds


class PixivRateLimitError(Exception):
    """Pixiv throttled the app API; ``retry_after`` is the seconds left on the cooldown."""

    def __init__(self, retry_after: float) -> None:
        self.retry_after = max(retry_after, 0.0)
        super().__init__(f"Pixiv rate limit, retry in {int(self.retry_after)}s")


async def pixiv_cooldown_remaining() -> float:
    """Seconds left on the shared rate-limit cooldown; 0 when clear or Redis is unreachable."""
    try:
        raw = await get_redis().get(_COOLDOWN_KEY)
        if raw is None:
            return 0.0
        until = float(raw.decode() if isinstance(raw, bytes) else raw)
    except Exception:
        return 0.0
    return max(until - time.time(), 0.0)


async def _start_cooldown() -> float:
    """Record a cooldown after a throttled response and return its length in seconds."""
    until = time.time() + _RATE_LIMIT_COOLDOWN
    try:
        await get_redis().setex(_COOLDOWN_KEY, _RATE_LIMIT_COOLDOWN, str(until))
    except Exception:
        logger.warning("Could not record the Pixiv rate-limit cooldown", exc_info=True)
    return float(_RATE_LIMIT_COOLDOWN)


def _is_rate_limit_body(result: Any) -> bool:
    """True for pixivpy3's parsed ``{"error": {"message": "Rate Limit"}}`` response."""
    if not isinstance(result, Mapping):
        return False
    error = result.get("error")
    if not error:
        return False
    if isinstance(error, Mapping):
        text = f"{error.get('message', '')} {error.get('user_message', '')}"
    else:
        text = str(error)
    return "rate limit" in text.lower()


def _token_keys(refresh_token: str) -> tuple[str, str]:
    """Redis keys for one refresh token: (cached access token, refresh lock).

    Keyed by a digest of the refresh token because an access token belongs to
    the account that minted it; two stored accounts must never share one.
    """
    digest = hashlib.sha256(refresh_token.encode()).hexdigest()[:16]
    return f"{_TOKEN_KEY_PREFIX}:{digest}", f"{_LOCK_KEY_PREFIX}:{digest}"


class PixivClient:
    """
    Async Pixiv API client wrapping pixivpy3 (synchronous library).

    All pixivpy3 calls are wrapped with asyncio.to_thread() to avoid
    blocking the event loop.  Use as an async context manager.

    Example:
        async with PixivClient(refresh_token) as client:
            result = await client.search_illust("hololive")
    """

    def __init__(self, refresh_token: str) -> None:
        self.refresh_token = refresh_token
        self._api: AppPixivAPI | None = None
        self._img_http: httpx.AsyncClient | None = None

    async def __aenter__(self) -> PixivClient:
        self._api = new_app_api()
        try:
            await self._ensure_token()
        except BaseException:
            await self.__aexit__()
            raise
        self._img_http = _get_shared_img_http()
        return self

    async def __aexit__(self, *_) -> None:
        # The image httpx client is shared and managed externally, but each
        # pixivpy session is ours: an author sync opens one client per work,
        # and unclosed sessions leak pooled sockets until "Too many open files".
        api, self._api = self._api, None
        if api is not None:
            api.requests.close()

    def _api_or_raise(self) -> AppPixivAPI:
        """Return the initialized pixivpy client."""
        if self._api is None:
            raise RuntimeError("PixivClient must be used as an async context manager")
        return self._api

    def _image_client_or_raise(self) -> httpx.AsyncClient:
        """Return the initialized shared image client."""
        if self._img_http is None:
            raise RuntimeError("PixivClient must be used as an async context manager")
        return self._img_http

    # ── Token management ─────────────────────────────────────────────

    async def _ensure_token(self) -> None:
        """Load access token from Redis cache or refresh via pixivpy3."""
        r = get_redis()
        token_key, lock_key = _token_keys(self.refresh_token)
        cached = await r.get(token_key)
        if cached:
            access_token = cached.decode() if isinstance(cached, bytes) else cached
            await asyncio.to_thread(self._api_or_raise().set_auth, access_token, self.refresh_token)
            return

        # Acquire a Redis lock to prevent concurrent refreshes
        lock_acquired = await r.set(lock_key, "1", nx=True, ex=_LOCK_TIMEOUT)
        if not lock_acquired:
            # Another instance is refreshing — wait with jitter to avoid stampede (#202/#203)
            deadline = time.monotonic() + _LOCK_TIMEOUT
            while time.monotonic() < deadline:
                await asyncio.sleep(0.1 + secrets.randbelow(50) / 1000)
                cached = await r.get(token_key)
                if cached:
                    access_token = cached.decode() if isinstance(cached, bytes) else cached
                    await asyncio.to_thread(self._api_or_raise().set_auth, access_token, self.refresh_token)
                    return
            raise PermissionError("Pixiv token refresh timed out waiting for lock")

        try:
            await self._refresh_token()
        finally:
            await r.delete(lock_key)

    async def _refresh_token(self) -> None:
        """Call pixivpy3 auth and cache the resulting access token."""
        r = get_redis()
        try:
            token_response = await asyncio.to_thread(self._api_or_raise().auth, refresh_token=self.refresh_token)
        except Exception as exc:
            raise PermissionError(f"Pixiv token invalid or expired: {exc}") from exc

        if not token_response or not hasattr(token_response, "access_token"):
            raise PermissionError("Pixiv token invalid or expired")

        access_token = token_response.access_token
        await r.setex(_token_keys(self.refresh_token)[0], _TOKEN_TTL, access_token)
        logger.info("Pixiv access token refreshed, cached for %ds", _TOKEN_TTL)

    async def _call(self, fn, *args, **kwargs):
        """
        Wrap a synchronous pixivpy3 call with to_thread().
        On 403 (token expired mid-session), flush cache and retry once.
        Raises PixivRateLimitError while Pixiv is throttling us, without
        sending the request when the shared cooldown is still running.
        """
        remaining = await pixiv_cooldown_remaining()
        if remaining > 0:
            raise PixivRateLimitError(remaining)
        try:
            result = await asyncio.to_thread(fn, *args, **kwargs)
        except Exception as exc:
            msg = str(exc).lower()
            if "rate limit" in msg:
                raise PixivRateLimitError(await _start_cooldown()) from exc
            if "403" in msg or "invalid_grant" in msg or "invalid_token" in msg:
                logger.warning("Pixiv token expired mid-session, retrying refresh")
                r = get_redis()
                await r.delete(_token_keys(self.refresh_token)[0])
                try:
                    await self._refresh_token()
                    result = await asyncio.to_thread(fn, *args, **kwargs)
                except PermissionError:
                    raise
                except Exception as exc2:
                    raise PermissionError(f"Pixiv request failed after token refresh: {exc2}") from exc2
            else:
                raise
        if _is_rate_limit_body(result):
            logger.warning("Pixiv rate limit hit, cooling down for %ds", _RATE_LIMIT_COOLDOWN)
            raise PixivRateLimitError(await _start_cooldown())
        return result

    # ── Normalisation helpers ─────────────────────────────────────────

    @staticmethod
    def _image_urls(illust: dict) -> dict:
        """Extract all relevant image URLs from an illust dict."""
        urls = illust.get("image_urls") or {}
        meta = illust.get("meta_single_page") or {}
        # For multi-page illusts, original is in meta_pages[0]
        meta_pages = illust.get("meta_pages") or []
        if meta_pages:
            first_page_urls = meta_pages[0].get("image_urls") or {}
            original = first_page_urls.get("original", urls.get("large", ""))
        else:
            original = meta.get("original_image_url", urls.get("large", ""))

        return {
            "square_medium": urls.get("square_medium", ""),
            "medium": urls.get("medium", ""),
            "large": urls.get("large", ""),
            "original": original,
        }

    @staticmethod
    def _normalize_illust(illust) -> dict:
        """Normalise a pixivpy3 illust object/dict to our internal format."""
        if not isinstance(illust, dict) and hasattr(illust, "__dict__"):
            illust = illust.__dict__

        user = illust.get("user") or {}
        if not isinstance(user, dict) and hasattr(user, "__dict__"):
            user = user.__dict__

        user_image_urls = user.get("profile_image_urls") or {}
        if not isinstance(user_image_urls, dict) and hasattr(user_image_urls, "__dict__"):
            user_image_urls = user_image_urls.__dict__

        tags_raw = illust.get("tags") or []
        tags = []
        for t in tags_raw:
            if not isinstance(t, dict) and hasattr(t, "__dict__"):
                t = t.__dict__
            tags.append(
                {
                    "name": t.get("name", ""),
                    "translated_name": t.get("translated_name"),
                }
            )

        image_urls_raw = illust.get("image_urls") or {}
        if not isinstance(image_urls_raw, dict) and hasattr(image_urls_raw, "__dict__"):
            image_urls_raw = image_urls_raw.__dict__

        meta_single = illust.get("meta_single_page") or {}
        if not isinstance(meta_single, dict) and hasattr(meta_single, "__dict__"):
            meta_single = meta_single.__dict__

        meta_pages_raw = illust.get("meta_pages") or []
        meta_pages = []
        for mp in meta_pages_raw:
            if not isinstance(mp, dict) and hasattr(mp, "__dict__"):
                mp = mp.__dict__
            mp_urls = mp.get("image_urls") or {}
            if not isinstance(mp_urls, dict) and hasattr(mp_urls, "__dict__"):
                mp_urls = mp_urls.__dict__
            meta_pages.append({"image_urls": mp_urls})

        if meta_pages:
            first_urls = meta_pages[0].get("image_urls") or {}
            original = first_urls.get("original", image_urls_raw.get("large", ""))
        else:
            original = meta_single.get("original_image_url", image_urls_raw.get("large", ""))

        return {
            "id": illust.get("id"),
            "title": illust.get("title", ""),
            "type": illust.get("type", "illust"),
            "image_urls": {
                "square_medium": image_urls_raw.get("square_medium", ""),
                "medium": image_urls_raw.get("medium", ""),
                "large": image_urls_raw.get("large", ""),
                "original": original,
            },
            "caption": illust.get("caption", ""),
            "user": {
                "id": user.get("id"),
                "name": user.get("name", ""),
                "account": user.get("account", ""),
                "profile_image": user_image_urls.get("medium", ""),
            },
            "tags": tags,
            "create_date": illust.get("create_date", ""),
            "page_count": illust.get("page_count", 1),
            "width": illust.get("width", 0),
            "height": illust.get("height", 0),
            "sanity_level": illust.get("sanity_level", 0),
            "total_view": illust.get("total_view", 0),
            "total_bookmarks": illust.get("total_bookmarks", 0),
            "is_bookmarked": illust.get("is_bookmarked", False),
            "meta_pages": meta_pages,
        }

    @staticmethod
    def _normalize_user(user_detail_response) -> dict:
        """Normalise a pixivpy3 user_detail response to our internal format."""
        if not isinstance(user_detail_response, dict) and hasattr(user_detail_response, "__dict__"):
            user_detail_response = user_detail_response.__dict__

        user = user_detail_response.get("user") or {}
        if not isinstance(user, dict) and hasattr(user, "__dict__"):
            user = user.__dict__

        profile = user_detail_response.get("profile") or {}
        if not isinstance(profile, dict) and hasattr(profile, "__dict__"):
            profile = profile.__dict__

        profile_image_urls = user.get("profile_image_urls") or {}
        if not isinstance(profile_image_urls, dict) and hasattr(profile_image_urls, "__dict__"):
            profile_image_urls = profile_image_urls.__dict__

        return {
            "id": user.get("id"),
            "name": user.get("name", ""),
            "account": user.get("account", ""),
            "profile_image": profile_image_urls.get("medium", ""),
            "comment": user.get("comment", ""),
            "total_illusts": profile.get("total_illusts", 0),
            "total_manga": profile.get("total_manga", 0),
            "total_novels": profile.get("total_novels", 0),
            "is_followed": bool(user.get("is_followed", False)),
        }

    @staticmethod
    def _next_offset(response) -> int | None:
        """Extract offset from next_url in a pixivpy3 paginated response."""
        if not isinstance(response, dict) and hasattr(response, "__dict__"):
            response = response.__dict__
        next_url = response.get("next_url")
        if not next_url:
            return None
        try:
            qs = parse_qs(urlparse(next_url).query)
            offset_vals = qs.get("offset", [])
            max_bookmark_id_vals = qs.get("max_bookmark_id", [])
            if offset_vals:
                return int(offset_vals[0])
            if max_bookmark_id_vals:
                return int(max_bookmark_id_vals[0])
        except ValueError, KeyError:
            pass
        return None

    def _normalize_illust_list(self, response) -> dict:
        """Normalise a paginated illust list response."""
        if not isinstance(response, dict) and hasattr(response, "__dict__"):
            response = response.__dict__
        illusts_raw = response.get("illusts") or []
        return {
            "illusts": [self._normalize_illust(i) for i in illusts_raw],
            "next_offset": self._next_offset(response),
        }

    # ── Public API ────────────────────────────────────────────────────

    async def search_illust(
        self,
        word: str,
        sort: str = "date_desc",
        search_target: str = "partial_match_for_tags",
        duration: str | None = None,
        offset: int = 0,
    ) -> dict:
        """Search illustrations. Returns {illusts, next_offset}."""
        kwargs = {
            "word": word,
            "sort": sort,
            "search_target": search_target,
            "offset": offset,
        }
        if duration:
            kwargs["duration"] = duration

        result = await self._call(self._api_or_raise().search_illust, **kwargs)
        return self._normalize_illust_list(result)

    async def illust_detail(self, illust_id: int) -> dict:
        """Get illustration detail. Returns normalized illust dict."""
        result = await self._call(self._api_or_raise().illust_detail, illust_id)
        if not isinstance(result, dict) and hasattr(result, "__dict__"):
            result = result.__dict__
        illust = result.get("illust")
        if not illust:
            raise ValueError(f"Illust {illust_id} not found")
        return self._normalize_illust(illust)

    async def user_detail(self, user_id: int) -> dict:
        """Get user profile info. Returns normalized user dict."""
        result = await self._call(self._api_or_raise().user_detail, user_id)
        return self._normalize_user(result)

    async def user_illusts(
        self,
        user_id: int,
        type: str | None = "illust",
        offset: int = 0,
    ) -> dict:
        """Get user illustrations. Returns {illusts, next_offset}."""
        kwargs: dict[str, object] = {"offset": offset}
        if type is not None:
            kwargs["type"] = type
        result = await self._call(self._api_or_raise().user_illusts, user_id, **kwargs)
        return self._normalize_illust_list(result)

    async def user_bookmarks(
        self,
        user_id: int,
        restrict: str = "public",
        offset: int = 0,
    ) -> dict:
        """Get user bookmarks. Returns {illusts, next_offset}."""
        kwargs: dict[str, object] = {"restrict": restrict}
        if offset > 0:
            kwargs["max_bookmark_id"] = offset
        result = await self._call(self._api_or_raise().user_bookmarks_illust, user_id, **kwargs)
        return self._normalize_illust_list(result)

    async def illust_follow(
        self,
        restrict: str = "public",
        offset: int = 0,
    ) -> dict:
        """Get following feed (new works from followed artists). Returns {illusts, next_offset}."""
        result = await self._call(self._api_or_raise().illust_follow, restrict=restrict, offset=offset)
        return self._normalize_illust_list(result)

    async def user_following(
        self,
        user_id: int,
        restrict: str = "public",
        offset: int = 0,
    ) -> dict:
        """Get user following list. Returns {user_previews, next_offset}."""
        result = await self._call(self._api_or_raise().user_following, user_id, restrict=restrict, offset=offset)
        if not isinstance(result, dict) and hasattr(result, "__dict__"):
            result = result.__dict__

        user_previews_raw = result.get("user_previews") or []
        user_previews = []
        for up in user_previews_raw:
            if not isinstance(up, dict) and hasattr(up, "__dict__"):
                up = up.__dict__
            user = up.get("user") or {}
            if not isinstance(user, dict) and hasattr(user, "__dict__"):
                user = user.__dict__
            profile_image_urls = user.get("profile_image_urls") or {}
            if not isinstance(profile_image_urls, dict) and hasattr(profile_image_urls, "__dict__"):
                profile_image_urls = profile_image_urls.__dict__
            illusts_raw = up.get("illusts") or []
            user_previews.append(
                {
                    "user": {
                        "id": user.get("id"),
                        "name": user.get("name", ""),
                        "account": user.get("account", ""),
                        "profile_image": profile_image_urls.get("medium", ""),
                    },
                    "illusts": [self._normalize_illust(i) for i in illusts_raw],
                }
            )

        return {
            "user_previews": user_previews,
            "next_offset": self._next_offset(result),
        }

    async def illust_bookmark_detail(self, illust_id: int) -> dict:
        """Get bookmark detail for an illust. Returns {is_bookmarked, restrict}."""
        result = await self._call(self._api_or_raise().illust_bookmark_detail, illust_id=illust_id)
        if not isinstance(result, dict) and hasattr(result, "__dict__"):
            result = result.__dict__
        detail = result.get("bookmark_detail") or {}
        if not isinstance(detail, dict) and hasattr(detail, "__dict__"):
            detail = detail.__dict__
        return {
            "is_bookmarked": bool(detail.get("is_bookmarked", False)),
            "restrict": detail.get("restrict", "public"),
        }

    async def illust_bookmark_add(self, illust_id: int, restrict: str = "public") -> None:
        """Add bookmark for an illust."""
        await self._call(self._api_or_raise().illust_bookmark_add, illust_id=illust_id, restrict=restrict)

    async def illust_ranking(
        self,
        mode: str = "day",
        date: str | None = None,
        offset: int = 0,
    ) -> dict:
        """Get ranking illusts via App API. Returns {illusts, next_offset}."""
        kwargs: dict = {"mode": mode, "offset": offset}
        if date:
            kwargs["date"] = date
        result = await self._call(self._api_or_raise().illust_ranking, **kwargs)
        return self._normalize_illust_list(result)

    async def illust_bookmark_delete(self, illust_id: int) -> None:
        """Delete bookmark for an illust."""
        await self._call(self._api_or_raise().illust_bookmark_delete, illust_id=illust_id)

    async def user_follow_add(self, user_id: int, restrict: str = "public") -> None:
        """Follow a user on Pixiv."""
        await self._call(self._api_or_raise().user_follow_add, user_id=user_id, restrict=restrict)

    async def user_follow_delete(self, user_id: int) -> None:
        """Unfollow a user on Pixiv."""
        await self._call(self._api_or_raise().user_follow_delete, user_id=user_id)

    async def download_image(self, url: str) -> tuple[bytes, str]:
        """
        Proxy-download a pximg.net image via httpx with Referer header.
        Returns (bytes, media_type).
        """
        resp = await self._image_client_or_raise().get(url)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "image/jpeg").split(";")[0].strip()
        return resp.content, content_type
