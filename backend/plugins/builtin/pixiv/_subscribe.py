"""Pixiv subscription check for the Subscribable protocol."""

import logging
from datetime import UTC, datetime

from plugins.models import NewWork

logger = logging.getLogger(__name__)

async def check_pixiv_new_works(
    artist_id: str,
    last_known: str | None,
    credentials: dict | None,
) -> list[NewWork]:
    """Check a Pixiv artist for new works since last_known illust ID.

    Args:
        artist_id: Pixiv user ID (numeric string)
        last_known: ID of the last known illust (or None for first check)
        credentials: dict with "refresh_token" key, or a plain refresh token string

    Returns:
        List of NewWork objects for works newer than last_known.
    """
    from services.pixiv_client import PixivClient

    if not credentials:
        return []

    refresh_token = credentials if isinstance(credentials, str) else credentials.get("refresh_token", "")
    if not refresh_token:
        return []

    try:
        async with PixivClient(refresh_token) as client:
            data = await client.user_illusts(int(artist_id))
            illusts = data.get("illusts", [])
    except Exception as exc:
        logger.error("[pixiv_subscribe] failed to fetch user %s illusts: %s", artist_id, exc)
        return []

    if not illusts:
        return []

    new_works: list[NewWork] = []
    for ill in illusts:
        ill_id = str(ill.get("id", ""))
        if last_known and ill_id == last_known:
            break

        posted_at: datetime | None = None
        raw_date = ill.get("create_date")
        if raw_date:
            try:
                posted_at = datetime.fromisoformat(str(raw_date))
            except ValueError, TypeError:
                pass

        # Get thumbnail URL
        images = ill.get("image_urls") or {}
        thumbnail = images.get("square_medium") or images.get("medium")

        new_works.append(NewWork(
            url=f"https://www.pixiv.net/artworks/{ill_id}",
            title=ill.get("title", ""),
            source_id=ill_id,
            thumbnail_url=thumbnail,
            posted_at=posted_at,
        ))

    return new_works
