"""E-Hentai subscription check for the Subscribable protocol."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from plugins.models import NewWork

logger = logging.getLogger(__name__)

MAX_PAGES = 10
PAGE_DELAY = 3  # seconds between page fetches


async def check_eh_new_works(
    query: str,              # EH search query (e.g. "uploader:Foo", "female:catgirl")
    last_known: str | None,  # last seen max gid (string), None = first check
    credentials: dict | None,
) -> list[NewWork]:
    """Check E-Hentai for new galleries matching query since last_known gid.

    Args:
        query: EH search query string (e.g. "uploader:Foo", "female:catgirl")
        last_known: string representation of the last seen max gid, or None for
                    first check (only takes first page)
        credentials: dict with cookie keys (ipb_member_id, ipb_pass_hash, etc.),
                     a JSON-encoded string of the same, or None for anonymous

    Returns:
        List of NewWork objects for galleries newer than last_known, newest-first.
    """
    # Parse credentials into a cookies dict.
    if not credentials:
        cookies: dict = {}
    elif isinstance(credentials, str):
        try:
            cookies = json.loads(credentials)
        except (json.JSONDecodeError, TypeError):
            logger.warning("[eh_subscribe] credentials JSON is malformed, using empty cookies")
            cookies = {}
    else:
        cookies = credentials

    last_known_gid: int | None = int(last_known) if last_known else None

    new_works: list[NewWork] = []

    try:
        from core.config import settings
        from core.redis_client import get_redis
        from services.eh_client import EhClient

        # Determine use_ex: Redis setting → config → igneous cookie presence.
        # Anonymous access must always use e-hentai.org.
        redis = get_redis()
        pref = await redis.get("setting:eh_use_ex")
        if pref is not None:
            use_ex = pref == b"1"
        else:
            use_ex = settings.eh_use_ex or bool(cookies.get("igneous"))

        if not cookies:
            use_ex = False

        async with EhClient(cookies, use_ex) as client:
            next_gid: int | None = None
            first_check = last_known_gid is None

            for page_num in range(MAX_PAGES):
                if page_num > 0:
                    await asyncio.sleep(PAGE_DELAY)

                result = await client.search(query=query, next_gid=next_gid)
                galleries = result.get("galleries", [])

                if not galleries:
                    break

                found_boundary = False
                for gallery in galleries:
                    gid = gallery.get("gid")
                    if gid is None:
                        continue

                    if last_known_gid is not None and gid <= last_known_gid:
                        found_boundary = True
                        break

                    token = gallery.get("token", "")
                    title = gallery.get("title", "")
                    thumb = gallery.get("thumb")

                    posted_at: datetime | None = None
                    posted_raw = gallery.get("posted_at")
                    if posted_raw:
                        try:
                            posted_at = datetime.fromtimestamp(int(posted_raw), tz=timezone.utc)
                        except (ValueError, TypeError, OSError):
                            pass

                    url = f"https://e-hentai.org/g/{gid}/{token}/"
                    new_works.append(NewWork(
                        url=url,
                        title=title,
                        source_id=str(gid),
                        thumbnail_url=thumb,
                        posted_at=posted_at,
                    ))

                # First check: only take first page, do not paginate.
                if first_check:
                    break

                if found_boundary:
                    break

                cursor = result.get("next_gid")
                if cursor is None:
                    break

                next_gid = cursor

                if page_num == MAX_PAGES - 1:
                    logger.warning(
                        "[eh_subscribe] reached MAX_PAGES=%d without catching up to last_known gid=%s "
                        "for query=%r; some galleries may be missed",
                        MAX_PAGES,
                        last_known,
                        query,
                    )

    except Exception as exc:
        logger.error("[eh_subscribe] error fetching results for query=%r: %s", query, exc, exc_info=True)
        return []

    return new_works
