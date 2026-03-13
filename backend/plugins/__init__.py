"""Plugin system initialization."""

from plugins.registry import plugin_registry


async def init_plugins() -> None:
    """Register all built-in plugins. Called during app startup and worker startup."""
    from plugins.builtin.gallery_dl.source import GalleryDlPlugin
    from plugins.builtin.ehentai.browse import EhBrowsePlugin
    from plugins.builtin.ehentai.source import EhSourcePlugin
    from plugins.builtin.pixiv.source import PixivSourcePlugin
    from plugins.builtin.pixiv._browse import PixivBrowsePlugin

    plugin_registry.register(GalleryDlPlugin())
    plugin_registry.register(EhBrowsePlugin())
    # EH source is registered but gallery-dl fallback handles most downloads
    plugin_registry.register(EhSourcePlugin())
    # Pixiv native downloader — takes precedence over gallery-dl for pixiv.net URLs
    plugin_registry.register(PixivSourcePlugin())
    plugin_registry.register(PixivBrowsePlugin())

    # Register gallery-dl subscribable proxies for sites that don't have native plugins
    from plugins.builtin.gallery_dl._sites import GDL_SITES
    from plugins.builtin.gallery_dl._subscribe import GalleryDlSubscribableProxy

    gdl = plugin_registry._plugins.get("gallery_dl")
    if gdl:
        for site_cfg in GDL_SITES:
            if site_cfg.subscribe_id_key is None:
                continue
            source_id = site_cfg.source_id
            # Don't override native plugin subscribables (e.g., ehentai, pixiv)
            # Also skip duplicate source_ids (e.g., x.com duplicates twitter.com)
            if not plugin_registry.get_subscribable(source_id):
                proxy = GalleryDlSubscribableProxy(source_id, gdl.meta)
                plugin_registry.register_subscribable_proxy(source_id, proxy)
