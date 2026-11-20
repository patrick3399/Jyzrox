"""Shared router, helpers and header builders for the Pixiv browse routes."""

from fastapi import APIRouter, Request

from core.client_identity import browser_headers
from core.errors import api_error, parse_accept_language
from services.credential import get_credential
from services.pixiv_client import PixivClient

_browse_router = APIRouter(tags=["pixiv"])


def _locale(request: Request) -> str:
    return parse_accept_language(request.headers.get("accept-language"))


# ── Client factory ────────────────────────────────────────────────────


async def _make_client(locale: str = "en") -> PixivClient:
    """Load Pixiv refresh_token from DB credentials and return a client."""
    refresh_token = await get_credential("pixiv")
    if not refresh_token:
        raise api_error(400, "pixiv_not_configured", locale)
    return PixivClient(refresh_token=refresh_token)


_PIXIV_ORIGIN = "https://www.pixiv.net"


def _ajax_headers() -> dict[str, str]:
    """A fetch() made by a www.pixiv.net page, without a Pixiv account.

    Requests made with an account go through PixivClient, which presents the
    Pixiv app identity instead.
    """
    return browser_headers("fetch", site="same-origin", referer=f"{_PIXIV_ORIGIN}/")


def _pximg_headers() -> dict[str, str]:
    """An <img> on www.pixiv.net loading from i.pximg.net."""
    return browser_headers("image", site="cross-site", referer=f"{_PIXIV_ORIGIN}/")


# ── Media type detection ──────────────────────────────────────────────


def _detect_media_type(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"
