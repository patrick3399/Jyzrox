"""Plugin registry — singleton that holds all registered plugins."""

import logging
from typing import Any

from plugins.base import (
    Browsable,
    BrowsePlugin,
    CredentialProvider,
    Downloadable,
    HasMeta,
    Parseable,
    SourcePlugin,
    Taggable,
    TaggerPlugin,
)
from plugins.models import PluginMeta, SiteInfo

logger = logging.getLogger(__name__)

class PluginRegistry:
    def __init__(self) -> None:
        # Legacy ABC dicts (preserved for backward compatibility)
        self._sources: dict[str, SourcePlugin] = {}
        self._browsers: dict[str, BrowsePlugin] = {}
        self._taggers: dict[str, TaggerPlugin] = {}
        self._fallback: SourcePlugin | None = None

        # Protocol capability tracking — maps source_id → specific plugin object
        self._plugins: dict[str, Any] = {}
        self._downloadable: dict[str, Any] = {}
        self._browsable: dict[str, Any] = {}
        self._parseable: dict[str, Any] = {}
        self._credential_providers: dict[str, Any] = {}
        self._taggable: dict[str, Any] = {}
        self._site_index: dict[str, SiteInfo] = {}

    def register(self, plugin: SourcePlugin | BrowsePlugin | TaggerPlugin) -> None:
        """Register a plugin. A plugin may implement multiple ABCs."""
        sid = plugin.meta.source_id

        # Legacy ABC checks (preserved)
        if isinstance(plugin, SourcePlugin):
            if sid == "gallery_dl":
                self._fallback = plugin
            self._sources[sid] = plugin
            logger.info("Registered source plugin: %s", sid)
        if isinstance(plugin, BrowsePlugin):
            self._browsers[sid] = plugin
            logger.info("Registered browse plugin: %s", sid)
        if isinstance(plugin, TaggerPlugin):
            self._taggers[sid] = plugin
            logger.info("Registered tagger plugin: %s", sid)

        # Protocol capability probing — each maps sid → the specific plugin object
        if isinstance(plugin, HasMeta):
            self._plugins[sid] = plugin
            # Build site index from supported_sites
            for site in plugin.meta.supported_sites:
                self._site_index[site.domain] = site
        if isinstance(plugin, Downloadable):
            self._downloadable[sid] = plugin
        if isinstance(plugin, Browsable):
            self._browsable[sid] = plugin
        if isinstance(plugin, Parseable):
            self._parseable[sid] = plugin
        if isinstance(plugin, CredentialProvider):
            self._credential_providers[sid] = plugin
        if isinstance(plugin, Taggable):
            self._taggable[sid] = plugin

    async def get_handler(self, url: str) -> SourcePlugin | None:
        """Return the first non-fallback source plugin that can handle the URL."""
        for plugin in self._sources.values():
            if plugin.meta.source_id == "gallery_dl":
                continue  # skip fallback in first pass
            if await plugin.can_handle(url):
                return plugin
        return None

    def get_fallback(self) -> SourcePlugin | None:
        """Return the gallery-dl fallback plugin."""
        return self._fallback

    def get_browser(self, source_id: str) -> BrowsePlugin | None:
        return self._browsers.get(source_id)

    def get_tagger(self, source_id: str) -> TaggerPlugin | None:
        return self._taggers.get(source_id)

    def list_plugins(self) -> list[PluginMeta]:
        """Return metadata for every registered plugin (deduplicated by source_id)."""
        seen: set[str] = set()
        result: list[PluginMeta] = []
        for plugins_dict in (self._sources, self._browsers, self._taggers):  # type: ignore[assignment]
            for sid, p in plugins_dict.items():
                if sid not in seen:
                    seen.add(sid)
                    result.append(p.meta)
        return result

    def list_browsers(self) -> dict[str, BrowsePlugin]:
        return dict(self._browsers)

    # ------------------------------------------------------------------
    # New Protocol-based methods
    # ------------------------------------------------------------------

    def detect_source(self, url: str) -> str | None:
        """Detect source_id from URL using site index, with gallery-dl fallback."""
        import urllib.parse
        try:
            netloc = urllib.parse.urlparse(url).netloc.lower()
        except Exception:
            return None
        if not netloc:
            return None

        # Primary: domain lookup from registered plugins
        for domain, site in self._site_index.items():
            if netloc == domain or netloc.endswith("." + domain):
                return site.source_id

        # Fallback: use gallery-dl extractor to detect category
        try:
            from gallery_dl import extractor as gdl_extractor
            from plugins.builtin.gallery_dl._sites import get_site_config
            ex = gdl_extractor.find(url)
            if ex and ex.category:
                cfg = get_site_config(ex.category)
                if cfg.source_id != "gallery_dl":
                    return cfg.source_id
                # Unregistered site: use gallery-dl's category directly
                return ex.category
        except Exception:
            pass

        return None

    def detect_source_info(self, url: str) -> SiteInfo | None:
        """Return SiteInfo for the given URL, with gallery-dl fallback."""
        import urllib.parse
        try:
            netloc = urllib.parse.urlparse(url).netloc.lower()
        except Exception:
            return None
        if not netloc:
            return None

        # Primary: domain lookup from registered plugins
        for domain, site in self._site_index.items():
            if netloc == domain or netloc.endswith("." + domain):
                return site

        # Fallback: use gallery-dl extractor to detect category
        try:
            from gallery_dl import extractor as gdl_extractor
            from plugins.builtin.gallery_dl._sites import get_site_config
            ex = gdl_extractor.find(url)
            if ex and ex.category:
                cfg = get_site_config(ex.category)
                if cfg.source_id != "gallery_dl":
                    # Known site in _sites.py: build SiteInfo from GdlSiteConfig
                    return SiteInfo(
                        domain=cfg.domain,
                        name=cfg.name,
                        source_id=cfg.source_id,
                        category=cfg.category,
                        has_tags=cfg.has_tags,
                    )
                # Unregistered site: build minimal SiteInfo using gallery-dl category
                return SiteInfo(
                    domain=netloc,
                    name=ex.category.capitalize(),
                    source_id=ex.category,
                    category="other",
                    has_tags=False,
                )
        except Exception:
            pass

        return None

    def get_all_sites(self) -> list[SiteInfo]:
        """Return all registered SiteInfo entries."""
        return list(self._site_index.values())

    def get_supported_sites_grouped(self) -> dict[str, list[dict]]:
        """Return sites grouped by category, deduplicated by source_id."""
        categories: dict[str, list[dict]] = {}
        seen: set[str] = set()
        for site in self._site_index.values():
            if site.source_id in seen:
                continue
            seen.add(site.source_id)
            categories.setdefault(site.category, []).append(site.model_dump())
        return categories

    def get_parser(self, source_id: str) -> Any:
        """Return the Parseable plugin for the given source_id, or None."""
        return self._parseable.get(source_id)

    def get_credential_provider(self, source_id: str) -> Any:
        return self._credential_providers.get(source_id)

    def list_credential_providers(self) -> list[tuple[str, list]]:
        result = []
        for sid, plugin in self._credential_providers.items():
            if hasattr(plugin, "credential_flows"):
                result.append((sid, plugin.credential_flows()))
        return result

    def get_browse_routers(self) -> list[tuple[str, Any]]:
        result = []
        for sid, plugin in self._browsable.items():
            if hasattr(plugin, "get_browse_router"):
                result.append((sid, plugin.get_browse_router()))
        return result

    def get_downloader(self, source_id: str) -> Any:
        return self._downloadable.get(source_id)

plugin_registry = PluginRegistry()
