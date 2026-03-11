"""Redis caching helpers with named operations for each cache key pattern."""

import json
import logging
from typing import Any

from core.redis_client import get_redis

logger = logging.getLogger(__name__)

# TTLs (seconds)
# EhViewer caches gallery detail in LruCache (no TTL, 25 entries) and
# pTokens persistently on disk.  We use generous Redis TTLs to match.
_TTL_GALLERY = 86400  # 24h — gallery metadata (rarely changes)
_TTL_IMAGELIST = 604800  # 7d  — image token list (pTokens are stable)
_TTL_PROXY_IMAGE = 86400  # 24h — proxied image bytes
_TTL_SEARCH = 300  # 5m  — search results

MAX_IMAGE_CACHE_BYTES = 5 * 1024 * 1024  # Skip caching images > 5 MB


# ── Generic helpers ──────────────────────────────────────────────────


async def get_json(key: str) -> Any | None:
    raw = await get_redis().get(key)
    return json.loads(raw) if raw else None


async def set_json(key: str, value: Any, ttl: int) -> None:
    await get_redis().setex(key, ttl, json.dumps(value, ensure_ascii=False))


async def get_bytes(key: str) -> bytes | None:
    return await get_redis().get(key)


async def set_bytes(key: str, value: bytes, ttl: int) -> None:
    if len(value) > MAX_IMAGE_CACHE_BYTES:
        logger.debug("Skip cache %s: %d bytes exceeds limit", key, len(value))
        return
    await get_redis().setex(key, ttl, value)


# ── Named cache operations ───────────────────────────────────────────


async def get_gallery_cache(gid: int) -> dict | None:
    return await get_json(f"eh:gallery:{gid}")


async def set_gallery_cache(gid: int, data: dict) -> None:
    await set_json(f"eh:gallery:{gid}", data, _TTL_GALLERY)


async def get_imagelist_cache(gid: int) -> dict | None:
    """Returns {str(page_num): image_page_token} or None."""
    return await get_json(f"eh:imagelist:{gid}")


async def set_imagelist_cache(gid: int, data: dict) -> None:
    await set_json(f"eh:imagelist:{gid}", data, _TTL_IMAGELIST)


async def get_preview_cache(gid: int) -> dict | None:
    """Returns {str(page_num): preview_url_or_sprite_info} or None."""
    return await get_json(f"eh:previews:{gid}")


async def set_preview_cache(gid: int, data: dict) -> None:
    await set_json(f"eh:previews:{gid}", data, _TTL_IMAGELIST)


async def get_proxied_image(gid: int, page: int) -> bytes | None:
    return await get_bytes(f"thumb:proxied:{gid}:{page}")


async def set_proxied_image(gid: int, page: int, data: bytes) -> None:
    await set_bytes(f"thumb:proxied:{gid}:{page}", data, _TTL_PROXY_IMAGE)


# ── Pixiv cache operations ───────────────────────────────────────────

_TTL_PIXIV_SEARCH = 300      # 5min
_TTL_PIXIV_ILLUST = 3600     # 1h
_TTL_PIXIV_USER = 1800       # 30min
_TTL_PIXIV_IMAGE = 86400     # 24h


async def get_pixiv_search_cache(key: str) -> dict | None:
    return await get_json(f"pixiv:search:{key}")


async def set_pixiv_search_cache(key: str, data: dict) -> None:
    await set_json(f"pixiv:search:{key}", data, _TTL_PIXIV_SEARCH)


async def get_pixiv_illust_cache(illust_id: int) -> dict | None:
    return await get_json(f"pixiv:illust:{illust_id}")


async def set_pixiv_illust_cache(illust_id: int, data: dict) -> None:
    await set_json(f"pixiv:illust:{illust_id}", data, _TTL_PIXIV_ILLUST)


async def get_pixiv_user_cache(user_id: int) -> dict | None:
    return await get_json(f"pixiv:user:{user_id}")


async def set_pixiv_user_cache(user_id: int, data: dict) -> None:
    await set_json(f"pixiv:user:{user_id}", data, _TTL_PIXIV_USER)


async def get_pixiv_image_cache(url_hash: str) -> bytes | None:
    return await get_bytes(f"pixiv:img:{url_hash}")


async def set_pixiv_image_cache(url_hash: str, data: bytes) -> None:
    await set_bytes(f"pixiv:img:{url_hash}", data, _TTL_PIXIV_IMAGE)


async def push_system_alert(message: str) -> None:
    r = get_redis()
    await r.lpush("system:alerts", message)
    await r.ltrim("system:alerts", 0, 49)  # Keep last 50


async def get_system_alerts() -> list[str]:
    r = get_redis()
    raw = await r.lrange("system:alerts", 0, 49)
    return [v.decode() if isinstance(v, bytes) else v for v in raw]


async def clear_system_alerts() -> None:
    await get_redis().delete("system:alerts")
