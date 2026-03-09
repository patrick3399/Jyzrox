"""E-Hentai BrowsePlugin.

Provides a generic plugin interface over the existing EhClient.  The actual
browsing endpoints in routers/eh.py are kept for backward compatibility; this
plugin exposes the same functionality through the unified plugin API.
"""

from __future__ import annotations

import json
import logging

from plugins.base import BrowsePlugin
from plugins.models import BrowseSchema, FieldDef, PluginMeta, SearchResult

logger = logging.getLogger(__name__)


class EhBrowsePlugin(BrowsePlugin):
    """BrowsePlugin for E-Hentai / ExHentai."""

    meta = PluginMeta(
        name="E-Hentai",
        source_id="ehentai",
        version="1.0.0",
        url_patterns=["e-hentai.org", "exhentai.org"],
        credential_schema=[
            FieldDef(
                name="ipb_member_id",
                field_type="text",
                label="ipb_member_id",
                required=True,
                placeholder="12345",
            ),
            FieldDef(
                name="ipb_pass_hash",
                field_type="password",
                label="ipb_pass_hash",
                required=True,
                placeholder="",
            ),
            FieldDef(
                name="sk",
                field_type="password",
                label="sk",
                required=False,
                placeholder="",
            ),
            FieldDef(
                name="igneous",
                field_type="password",
                label="igneous (ExHentai)",
                required=False,
                placeholder="",
            ),
        ],
        concurrency=3,
    )

    def browse_schema(self) -> BrowseSchema:
        return BrowseSchema(
            search_fields=[
                FieldDef(name="q", field_type="text", label="Search query", placeholder="artist:..., tag:..."),
                FieldDef(name="category", field_type="text", label="Category", placeholder="Doujinshi"),
                FieldDef(name="f_cats", field_type="text", label="Category bitmask (f_cats)"),
                FieldDef(name="advance", field_type="select", label="Advanced search"),
                FieldDef(name="adv_search", field_type="text", label="adv_search flags"),
                FieldDef(name="min_rating", field_type="text", label="Minimum rating (2-5)"),
                FieldDef(name="page_from", field_type="text", label="Min pages"),
                FieldDef(name="page_to", field_type="text", label="Max pages"),
                FieldDef(name="language", field_type="text", label="Language tag"),
            ],
            supports_favorites=True,
            supports_popular=True,
            supports_toplist=True,
        )

    async def search(
        self,
        params: dict,
        credentials: dict | None = None,
    ) -> SearchResult:
        """Run an EH search through EhClient."""
        from core.config import settings as app_settings
        from core.redis_client import get_redis
        from services.eh_client import EhClient

        cookies: dict = {}
        if credentials:
            if isinstance(credentials, str):
                try:
                    cookies = json.loads(credentials)
                except (json.JSONDecodeError, TypeError):
                    logger.warning("[eh_browse] malformed credentials JSON")
            else:
                cookies = credentials  # type: ignore[assignment]

        redis = get_redis()
        pref = await redis.get("setting:eh_use_ex")
        if pref is not None:
            use_ex = pref == b"1"
        else:
            use_ex = app_settings.eh_use_ex or bool(cookies.get("igneous"))

        client = EhClient(cookies=cookies, use_ex=use_ex)
        async with client:
            result = await client.search(
                query=params.get("q", ""),
                page=int(params.get("page", 0)),
                category=params.get("category"),
                f_cats=params.get("f_cats"),
                advance=bool(params.get("advance", False)),
                adv_search=int(params.get("adv_search", 0)),
                min_rating=params.get("min_rating"),
                page_from=params.get("page_from"),
                page_to=params.get("page_to"),
            )

        galleries = result.get("galleries", [])
        return SearchResult(
            galleries=galleries,
            total=result.get("total", len(galleries)),
            page=int(params.get("page", 0)),
            has_next=result.get("has_next", False),
            has_prev=result.get("has_prev", False),
            extra=result,
        )

    async def proxy_image(
        self,
        url: str,
        credentials: dict | None = None,
    ) -> tuple[bytes, str]:
        """Fetch image bytes via EhClient for proxying."""
        import httpx

        from services.eh_client import _detect_media_type

        cookies: dict = {}
        if credentials:
            if isinstance(credentials, str):
                try:
                    cookies = json.loads(credentials)
                except (json.JSONDecodeError, TypeError):
                    pass
            else:
                cookies = credentials  # type: ignore[assignment]

        async with httpx.AsyncClient(cookies=cookies, follow_redirects=True, timeout=30) as http:
            resp = await http.get(url)
            resp.raise_for_status()
            data = resp.content
            media_type = _detect_media_type(data)
            return data, media_type
