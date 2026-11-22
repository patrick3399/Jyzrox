"""Library split from routers/library.py (library_helpers)."""

import base64
import hashlib
import hmac
import json
from urllib.parse import unquote

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import gallery_access_filter
from core.gallery_helpers import (
    build_cover_map,
)
from db.models import (
    Gallery,
    UserFavorite,
    UserImageFavorite,
    UserRating,
    UserReadingList,
)
from services.gallery_lifecycle import (
    trash_scope,
)
from services.gallery_sort import encode_value

_build_cover_map = build_cover_map


def artist_display_name(artist_id: str | None, uploader: str | None) -> str:
    """Return the user-facing artist name without conflating EH uploader data."""
    clean_uploader = (uploader or "").strip()
    if not artist_id:
        return clean_uploader

    source, _, raw_name = artist_id.partition(":")
    if source == "ehentai" and raw_name:
        return raw_name
    if clean_uploader:
        return clean_uploader
    return raw_name or artist_id


def trash_filter(auth: dict):
    """Return WHERE clause for trash visibility: soft-deleted galleries the user can see."""
    return trash_scope(auth)


def cursor_secret() -> bytes:
    """Return the HMAC signing key for pagination cursors."""
    from core.keys import cursor_hmac_key

    return cursor_hmac_key()


def encode_cursor(gallery: Gallery, sort: str, value) -> str:
    """Encode sort key + id into a signed URL-safe base64 cursor string.

    ``value`` is the row's sort value (the viewer's rating for ``rating``); None
    encodes as JSON null (NULL row).

    Format: <base64url(json)>.<hmac-sha256-hex>
    """
    payload = {"id": gallery.id, "v": encode_value(value), "s": sort}
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    sig = hmac.new(_cursor_secret(), encoded.encode(), hashlib.sha256).hexdigest()
    return f"{encoded}.{sig}"


def decode_cursor(cursor: str) -> dict:
    """Decode and verify a signed cursor. Raises HTTP 400 if invalid or tampered."""
    if "." not in cursor:
        raise HTTPException(status_code=400, detail="Invalid cursor")
    # Split on the last dot so the base64 payload (which may contain dots in edge
    # cases due to padding) is kept intact; HMAC hex is always 64 hex chars.
    encoded, _, sig = cursor.rpartition(".")
    if not encoded or not sig:
        raise HTTPException(status_code=400, detail="Invalid cursor")
    expected_sig = hmac.new(_cursor_secret(), encoded.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_sig, sig):
        raise HTTPException(status_code=400, detail="Invalid cursor: signature mismatch")
    try:
        # Re-add stripped padding before decoding.
        padded = encoded + "=" * (4 - len(encoded) % 4)
        return json.loads(base64.urlsafe_b64decode(padded))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid cursor")


async def get_image_favorite_set(db: AsyncSession, user_id: int, image_ids: list[int]) -> set[int]:
    """Return set of image_ids that are favorited by this user."""
    if not image_ids:
        return set()
    result = await db.execute(
        select(UserImageFavorite.image_id).where(
            UserImageFavorite.user_id == user_id,
            UserImageFavorite.image_id.in_(image_ids),
        )
    )
    return {row[0] for row in result}


async def single_cover_thumb(db: AsyncSession, gallery_id: int, source: str) -> str | None:
    """Get cover thumbnail for a single gallery."""
    cover_map = await _build_cover_map(db, [gallery_id], {gallery_id: source})
    return cover_map.get(gallery_id)


async def user_gallery_state(db: AsyncSession, user_id: int, gallery_id: int) -> tuple[bool, int | None, bool]:
    """Return (is_favorited, my_rating, in_reading_list) for a user+gallery pair."""
    fav_row = await db.execute(
        select(UserFavorite).where(
            UserFavorite.user_id == user_id,
            UserFavorite.gallery_id == gallery_id,
        )
    )
    rating_row = await db.execute(
        select(UserRating.rating).where(
            UserRating.user_id == user_id,
            UserRating.gallery_id == gallery_id,
        )
    )
    rl_row = await db.execute(
        select(UserReadingList).where(
            UserReadingList.user_id == user_id,
            UserReadingList.gallery_id == gallery_id,
        )
    )
    return (
        fav_row.scalar_one_or_none() is not None,
        rating_row.scalar_one_or_none(),
        rl_row.scalar_one_or_none() is not None,
    )


async def get_or_404_by_source(db: AsyncSession, source: str, source_id: str, auth: dict | None = None) -> Gallery:
    """Fetch a gallery by (source, source_id) with optional access filter. Raises 404 if not found."""
    source_id = unquote(source_id)
    if auth is not None:
        stmt = select(Gallery).where(
            Gallery.source == source,
            Gallery.source_id == source_id,
            gallery_access_filter(auth),
        )
        g = (await db.execute(stmt)).scalar_one_or_none()
    else:
        stmt = select(Gallery).where(
            Gallery.source == source,
            Gallery.source_id == source_id,
        )
        g = (await db.execute(stmt)).scalar_one_or_none()
    if not g:
        raise HTTPException(status_code=404, detail="Gallery not found")
    return g


def check_write_access(auth: dict, gallery: Gallery) -> None:
    """Raise 403 if the caller cannot modify this gallery.

    Admins can modify any gallery. Members can modify galleries they created
    or unowned (legacy) galleries whose created_by_user_id is NULL.
    """
    if auth["role"] == "admin":
        return
    if gallery.created_by_user_id is None or gallery.created_by_user_id == auth["user_id"]:
        return
    raise HTTPException(status_code=403, detail="You do not have permission to modify this gallery")


_cursor_secret = cursor_secret
