"""Static site metadata lookup for gallery-dl-managed sources.

Routers must not import plugins.builtin internals (pre-commit gate 2 /
architecture risk #2); this wrapper is the blessed access path outside the
plugin package, so the plugin's internal layout can change without touching
router code.
"""

from plugins.builtin.gallery_dl._sites import GdlSiteConfig, get_site_config

__all__ = ["GdlSiteConfig", "get_site_config"]
