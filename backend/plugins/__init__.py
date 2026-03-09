"""Plugin system initialization."""

from plugins.registry import plugin_registry


async def init_plugins() -> None:
    """Register all built-in plugins. Called during app startup and worker startup."""
    from plugins.builtin.gallery_dl.source import GalleryDlPlugin
    from plugins.builtin.ehentai.browse import EhBrowsePlugin
    from plugins.builtin.ehentai.source import EhSourcePlugin

    plugin_registry.register(GalleryDlPlugin())
    plugin_registry.register(EhBrowsePlugin())
    # EH source is registered but gallery-dl fallback handles most downloads
    plugin_registry.register(EhSourcePlugin())
