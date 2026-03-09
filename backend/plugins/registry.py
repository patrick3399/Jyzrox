"""Plugin registry — singleton that holds all registered plugins."""

from __future__ import annotations

import logging

from plugins.base import BrowsePlugin, SourcePlugin, TaggerPlugin
from plugins.models import PluginMeta

logger = logging.getLogger(__name__)


class PluginRegistry:
    def __init__(self) -> None:
        self._sources: dict[str, SourcePlugin] = {}
        self._browsers: dict[str, BrowsePlugin] = {}
        self._taggers: dict[str, TaggerPlugin] = {}
        self._fallback: SourcePlugin | None = None

    def register(self, plugin: SourcePlugin | BrowsePlugin | TaggerPlugin) -> None:
        """Register a plugin. A plugin may implement multiple ABCs."""
        sid = plugin.meta.source_id
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


plugin_registry = PluginRegistry()
