"""Shared router and helpers for the E-Hentai browse routes."""

import json

from fastapi import APIRouter, Request
from sqlalchemy import select

from core.config import settings as app_settings
from core.database import async_session
from core.errors import parse_accept_language
from core.redis_client import get_redis
from db.models import BlockedTag
from services.credential import get_credential
from services.eh_client import EhClient

_browse_router = APIRouter(tags=["e-hentai"])


def _locale(request: Request) -> str:
    return parse_accept_language(request.headers.get("accept-language"))


# ── Blocked tag helpers ───────────────────────────────────────────────


async def _get_blocked_tags(user_id: int) -> set[str]:
    """Return set of 'namespace:name' blocked tag strings for the user."""
    async with async_session() as session:
        rows = (
            await session.execute(select(BlockedTag.namespace, BlockedTag.name).where(BlockedTag.user_id == user_id))
        ).all()
    return {f"{r.namespace}:{r.name}" for r in rows}


def _filter_blocked(galleries: list[dict], blocked: set[str]) -> list[dict]:
    """Filter out galleries that contain any blocked tag."""
    if not blocked:
        return galleries
    return [g for g in galleries if not blocked.intersection(set(g.get("tags", [])))]


async def _make_client() -> EhClient:
    """Load EH cookies from DB and return a configured client (guest if no creds)."""
    cred_json = await get_credential("ehentai")
    cookies = json.loads(cred_json) if cred_json else {}
    redis = get_redis()
    pref = await redis.get("setting:eh_use_ex")
    if pref is not None:
        use_ex = pref == b"1"
    else:
        use_ex = app_settings.eh_use_ex or bool(cookies.get("igneous"))
    return EhClient(cookies=cookies, use_ex=use_ex)


# ── Search ───────────────────────────────────────────────────────────
