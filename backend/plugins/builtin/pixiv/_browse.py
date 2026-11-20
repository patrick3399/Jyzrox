"""Pixiv browse plugin — provides the Browsable protocol and browse endpoints."""

import logging

from fastapi import APIRouter

from core.version import __version__
from plugins.base import BrowsePlugin
from plugins.builtin.pixiv._browse_common import _browse_router
from plugins.models import (
    BrowseSchema,
    CredentialFlow,
    CredentialStatus,
    FieldDef,
    PluginMeta,
    SearchResult,
    SiteInfo,
)
from services.pixiv_client import PixivClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PixivBrowsePlugin class
# ---------------------------------------------------------------------------


class PixivBrowsePlugin(BrowsePlugin):
    """BrowsePlugin + Browsable for Pixiv."""

    meta = PluginMeta(
        name="Pixiv",
        source_id="pixiv",
        version=__version__,
        description="Pixiv artwork browser",
        url_patterns=["pixiv.net"],
        credential_schema=[
            FieldDef(
                name="refresh_token",
                field_type="password",
                label="Refresh Token",
                required=True,
            ),
        ],
        supported_sites=[
            SiteInfo(domain="pixiv.net", name="Pixiv", source_id="pixiv", category="art", has_tags=True),
        ],
        concurrency=4,
        semaphore_key="pixiv",
    )

    def browse_schema(self) -> BrowseSchema:
        return BrowseSchema(
            search_fields=[
                FieldDef(
                    name="word",
                    field_type="text",
                    label="Search keyword",
                    required=True,
                    placeholder="character name, tag...",
                ),
                FieldDef(name="sort", field_type="select", label="Sort"),
                FieldDef(name="search_target", field_type="select", label="Search target"),
                FieldDef(name="duration", field_type="select", label="Duration"),
            ],
            supports_favorites=True,
            supports_popular=True,
        )

    async def search(self, params: dict, credentials: dict | None = None) -> SearchResult:
        """Run a Pixiv search through PixivClient."""
        refresh_token = ""
        if credentials:
            if isinstance(credentials, str):
                refresh_token = credentials
            elif isinstance(credentials, dict):
                refresh_token = credentials.get("refresh_token", "")

        if not refresh_token:
            return SearchResult(galleries=[], total=0)

        async with PixivClient(refresh_token) as client:
            result = await client.search_illust(
                word=params.get("word", ""),
                sort=params.get("sort", "date_desc"),
                search_target=params.get("search_target", "partial_match_for_tags"),
                duration=params.get("duration"),
                offset=int(params.get("offset", 0)),
            )

        illusts = result.get("illusts", [])
        return SearchResult(
            galleries=[{"illust": i} for i in illusts],
            total=len(illusts),
            has_next=bool(result.get("next_url")),
        )

    async def proxy_image(self, url: str, credentials: dict | None = None) -> tuple[bytes, str]:
        """Fetch image bytes via PixivClient for proxying."""
        refresh_token = ""
        if credentials:
            if isinstance(credentials, str):
                refresh_token = credentials
            elif isinstance(credentials, dict):
                refresh_token = credentials.get("refresh_token", "")

        async with PixivClient(refresh_token) as client:
            image_bytes, media_type = await client.download_image(url)
        return image_bytes, media_type

    # ------------------------------------------------------------------
    # CredentialProvider protocol
    # ------------------------------------------------------------------

    def credential_flows(self) -> list[CredentialFlow]:
        from plugins.builtin.pixiv._credentials import pixiv_credential_flows

        return pixiv_credential_flows()

    async def verify_credential(self, credentials: dict) -> CredentialStatus:
        from plugins.builtin.pixiv._credentials import verify_pixiv_credential

        return await verify_pixiv_credential(credentials)

    # ------------------------------------------------------------------
    # Browsable protocol method
    # ------------------------------------------------------------------

    def get_browse_router(self) -> APIRouter:
        """Return the Pixiv browse router."""
        return _browse_router


# Route registration: importing these modules attaches their routes to
# ``_browse_router``. The import order is the route registration order.
# isort: off
from plugins.builtin.pixiv import _browse_search  # noqa: E402, F401
from plugins.builtin.pixiv import _browse_illust  # noqa: E402, F401
from plugins.builtin.pixiv import _browse_collection  # noqa: E402, F401
from plugins.builtin.pixiv import _browse_user  # noqa: E402, F401
from plugins.builtin.pixiv import _browse_feed  # noqa: E402, F401
from plugins.builtin.pixiv._browse_common import _detect_media_type as _detect_media_type  # noqa: E402
from plugins.builtin.pixiv._browse_illust import _fetch_illust_public as _fetch_illust_public  # noqa: E402
# isort: on
