"""SauceNAO reverse image search client."""

import logging
import time

import httpx

from core.redis_client import get_redis

logger = logging.getLogger(__name__)

SAUCENAO_API_URL = "https://saucenao.com/search.php"

# Rate limit: 6 requests per 30 seconds (free tier)
_RATE_KEY = "saucenao:rate"
_RATE_LIMIT = 6
_RATE_WINDOW = 30


async def _check_rate_limit() -> bool:
    """Return True if under rate limit, False if exceeded. Atomic INCR-then-check."""
    redis = get_redis()
    pipe = redis.pipeline()
    pipe.incr(_RATE_KEY)
    pipe.expire(_RATE_KEY, _RATE_WINDOW, nx=True)
    results = await pipe.execute()
    return int(results[0]) <= _RATE_LIMIT


async def search_by_image(
    image_bytes: bytes,
    api_key: str,
    *,
    filename: str = "image.jpg",
    num_results: int = 8,
) -> list[dict]:
    """Search SauceNAO by uploading image bytes.

    Returns a list of result dicts with keys:
        similarity, source_url, title, author, source_name, thumbnail, ext_urls
    """
    if not await _check_rate_limit():
        raise RateLimitError("SauceNAO rate limit exceeded, please wait")

    params = {
        "api_key": api_key,
        "output_type": "2",  # JSON
        "numres": str(num_results),
    }

    start = time.monotonic()
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            SAUCENAO_API_URL,
            params=params,
            files={"file": (filename, image_bytes)},
        )
        resp.raise_for_status()

    elapsed = time.monotonic() - start
    logger.info("SauceNAO search completed in %.1fs", elapsed)

    data = resp.json()

    # Check for API-level errors
    header = data.get("header", {})
    if header.get("status", 0) < 0:
        msg = header.get("message", "Unknown SauceNAO error")
        raise SauceNaoError(msg)

    results = []
    for item in data.get("results", []):
        header = item.get("header", {})
        result_data = item.get("data", {})

        similarity = float(header.get("similarity", 0))
        thumbnail = header.get("thumbnail", "")
        index_name = header.get("index_name", "")

        ext_urls = result_data.get("ext_urls", [])
        source_url = ext_urls[0] if ext_urls else result_data.get("source", "")

        # Field names vary by SauceNAO index
        title = (
            result_data.get("title")
            or result_data.get("eng_name")
            or result_data.get("jp_name")
            or result_data.get("material")
            or ""
        )

        author = (
            result_data.get("member_name")
            or result_data.get("author_name")
            or result_data.get("creator")
            or result_data.get("author")
            or ""
        )
        # creator can be a list
        if isinstance(author, list):
            author = ", ".join(author)

        results.append({
            "similarity": similarity,
            "source_url": source_url,
            "title": title,
            "author": author,
            "source_name": index_name,
            "thumbnail": thumbnail,
            "ext_urls": ext_urls,
        })

    results.sort(key=lambda r: r["similarity"], reverse=True)
    return results


class SauceNaoError(Exception):
    """SauceNAO API returned an error."""


class RateLimitError(SauceNaoError):
    """Rate limit exceeded."""
