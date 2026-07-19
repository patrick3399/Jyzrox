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
    Previewable,
    Processable,
    Refreshable,
    SourcePlugin,
    Subscribable,
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
        self._processable: dict[str, Any] = {}
        self._previewable: dict[str, Any] = {}
        self._refreshable: dict[str, Any] = {}
        self._subscribable: dict[str, Any] = {}
        self._site_index: dict[str, SiteInfo] = {}

    @staticmethod
    def _owner_signature(plugin: Any) -> tuple:
        """Return the stable identity shared by split capability implementations."""
        meta = plugin.meta
        return (
            meta.name,
            meta.source_id,
            meta.version,
            tuple(sorted(meta.url_patterns)),
            tuple(sorted((site.domain, site.source_id) for site in meta.supported_sites)),
            tuple(sorted(field.name for field in meta.credential_schema)),
            meta.semaphore_key,
        )

    def _claim(self, bucket: dict[str, Any], sid: str, plugin: Any, capability_name: str) -> None:
        """Assign ``plugin`` to ``bucket[sid]``, guarding against silent overwrite.

        Two plugin objects legitimately share a source_id when a single logical
        source is split across a SourcePlugin/BrowsePlugin pair (e.g.
        ``EhBrowsePlugin`` + ``EhSourcePlugin``, both ``source_id="ehentai"``,
        both delegating to the same credential helpers). That pattern is
        detected via a stable owner signature (name, version, URL/site,
        credential-field, and semaphore identity) and tolerated as an
        idempotent re-claim. Descriptions and presentation-only field metadata
        may differ between the browse and source halves.
        What must never happen silently is a genuinely different plugin
        reusing an existing source_id and clobbering the capability that was
        already registered for it (HR-009).
        """
        existing = bucket.get(sid)
        if (
            existing is not None
            and existing is not plugin
            and self._owner_signature(existing) != self._owner_signature(plugin)
        ):
            raise ValueError(
                f"Duplicate source_id={sid!r} for {capability_name}: "
                f"{type(existing).__name__} ({existing.meta.name!r}) is already registered; "
                f"{type(plugin).__name__} ({plugin.meta.name!r}) attempted to overwrite it"
            )
        bucket[sid] = plugin

    def register(self, plugin: Any) -> None:
        """Register a plugin. A plugin may implement multiple ABCs."""
        sid = plugin.meta.source_id

        # Legacy ABC checks (preserved)
        if isinstance(plugin, SourcePlugin):
            if sid == "gallery_dl":
                self._fallback = plugin
            self._claim(self._sources, sid, plugin, "SourcePlugin")
            logger.info("Registered source plugin: %s", sid)
        if isinstance(plugin, BrowsePlugin):
            self._claim(self._browsers, sid, plugin, "BrowsePlugin")
            logger.info("Registered browse plugin: %s", sid)
        if isinstance(plugin, TaggerPlugin):
            self._claim(self._taggers, sid, plugin, "TaggerPlugin")
            logger.info("Registered tagger plugin: %s", sid)

        # Protocol capability probing — each maps sid → the specific plugin object
        if isinstance(plugin, HasMeta):
            self._claim(self._plugins, sid, plugin, "HasMeta")
            # Build site index from supported_sites, rejecting domain hijacks:
            # a domain already claimed by a *different* source_id indicates a
            # real registration conflict, not an intentional split-plugin pair.
            for site in plugin.meta.supported_sites:
                existing_site = self._site_index.get(site.domain)
                if existing_site is not None and existing_site.source_id != site.source_id:
                    raise ValueError(
                        f"Site domain conflict for {site.domain!r}: already mapped to "
                        f"source_id={existing_site.source_id!r}; {type(plugin).__name__} "
                        f"attempted to remap it to source_id={site.source_id!r}"
                    )
                self._site_index[site.domain] = site
        if isinstance(plugin, Downloadable):
            self._claim(self._downloadable, sid, plugin, "Downloadable")
        if isinstance(plugin, Browsable):
            self._claim(self._browsable, sid, plugin, "Browsable")
        if isinstance(plugin, Parseable):
            self._claim(self._parseable, sid, plugin, "Parseable")
        if isinstance(plugin, CredentialProvider):
            self._claim(self._credential_providers, sid, plugin, "CredentialProvider")
        if isinstance(plugin, Taggable):
            self._claim(self._taggable, sid, plugin, "Taggable")
        if isinstance(plugin, Processable):
            self._claim(self._processable, sid, plugin, "Processable")
        if isinstance(plugin, Previewable):
            self._claim(self._previewable, sid, plugin, "Previewable")
        if isinstance(plugin, Refreshable):
            self._claim(self._refreshable, sid, plugin, "Refreshable")
        if isinstance(plugin, Subscribable):
            self._claim(self._subscribable, sid, plugin, "Subscribable")

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
        return [plugin.meta for plugin in self._plugins.values()]

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

    def get_processor(self, source_id: str) -> Any:
        return self._processable.get(source_id)

    def get_previewer(self, source_id: str) -> Any:
        return self._previewable.get(source_id)

    def list_previewable(self) -> list[Any]:
        return list(self._previewable.values())

    def get_refresher(self, source_id: str) -> Any:
        return self._refreshable.get(source_id)

    def get_subscriber(self, source_id: str) -> Any:
        return self._subscribable.get(source_id)


plugin_registry = PluginRegistry()
