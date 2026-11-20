"""E-Hentai BrowsePlugin.

Provides a generic plugin interface over the existing EhClient.  The browse
endpoints previously in routers/eh.py are now owned by this module and
exposed via get_browse_router().
"""

import json
import logging
from urllib.parse import urlparse

from fastapi import APIRouter

from core.client_identity import browser_headers
from core.config import settings as app_settings
from core.redis_client import get_redis
from core.version import __version__
from plugins.base import BrowsePlugin
from plugins.builtin.ehentai._browse_common import _browse_router
from plugins.models import (
    BrowseSchema,
    CredentialFlow,
    CredentialStatus,
    FieldDef,
    PluginMeta,
    SearchResult,
    SiteInfo,
)
from services.browser_http import browser_client
from services.eh_client import EhClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# EhBrowsePlugin class
# ---------------------------------------------------------------------------


class EhBrowsePlugin(BrowsePlugin):
    """BrowsePlugin for E-Hentai / ExHentai."""

    meta = PluginMeta(
        name="E-Hentai",
        source_id="ehentai",
        version=__version__,
        description="E-Hentai / ExHentai gallery downloader",
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
        supported_sites=[
            SiteInfo(domain="e-hentai.org", name="E-Hentai", source_id="ehentai", category="gallery", has_tags=True),
            SiteInfo(domain="exhentai.org", name="ExHentai", source_id="ehentai", category="gallery", has_tags=True),
        ],
        concurrency=3,
        semaphore_key="ehentai",
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
        cookies: dict = {}
        if credentials:
            if isinstance(credentials, str):
                try:
                    cookies = json.loads(credentials)
                except json.JSONDecodeError, TypeError:
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
        from services.eh_client import detect_media_type

        cookies: dict = {}
        if credentials:
            if isinstance(credentials, str):
                try:
                    cookies = json.loads(credentials)
                except json.JSONDecodeError, TypeError:
                    pass
            else:
                cookies = credentials  # type: ignore[assignment]

        referer = "https://exhentai.org/" if "exhentai" in (urlparse(url).hostname or "") else "https://e-hentai.org/"
        async with browser_client(cookies=cookies, follow_redirects=True, timeout=30) as http:
            resp = await http.get(url, headers=browser_headers("image", site="cross-site", referer=referer))
            resp.raise_for_status()
            data = resp.content
            media_type = detect_media_type(data)
            return data, media_type

    # ------------------------------------------------------------------
    # CredentialProvider protocol
    # ------------------------------------------------------------------

    def credential_flows(self) -> list[CredentialFlow]:
        from plugins.builtin.ehentai._credentials import eh_credential_flows

        return eh_credential_flows()

    async def verify_credential(self, credentials: dict) -> CredentialStatus:
        from plugins.builtin.ehentai._credentials import verify_eh_credential

        return await verify_eh_credential(credentials)

    # ------------------------------------------------------------------
    # Browsable protocol method
    # ------------------------------------------------------------------

    def get_browse_router(self) -> APIRouter:
        """Return the EH browse router."""
        return _browse_router


# ---------------------------------------------------------------------------
# Browse router — formerly routers/eh.py
# ---------------------------------------------------------------------------


# Route registration: importing these modules attaches their routes to
# ``_browse_router``. The import order is the route registration order.
# isort: off
from plugins.builtin.ehentai import _browse_search  # noqa: E402, F401
from plugins.builtin.ehentai import _browse_listing  # noqa: E402, F401
from plugins.builtin.ehentai import _browse_gallery  # noqa: E402, F401
from plugins.builtin.ehentai import _browse_paginated  # noqa: E402, F401
from plugins.builtin.ehentai import _browse_proxy_favorites  # noqa: E402, F401
from plugins.builtin.ehentai import _browse_thumb  # noqa: E402, F401
from plugins.builtin.ehentai._browse_common import _make_client as _make_client  # noqa: E402
# isort: on
