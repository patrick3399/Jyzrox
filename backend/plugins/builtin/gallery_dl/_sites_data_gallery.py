"""gallery-dl site table: gallery, manga and filehost sites."""

from ._site_config import GdlSiteConfig

SITES_GALLERY_FILEHOST: tuple[GdlSiteConfig, ...] = (
    # ── Gallery ──
    GdlSiteConfig(
        domain="nhentai.net",
        source_id="nhentai",
        name="nhentai",
        category="gallery",
        has_tags=True,
        artist_from="tag",
    ),
    GdlSiteConfig(
        domain="hitomi.la",
        source_id="hitomi",
        name="Hitomi.la",
        category="gallery",
        has_tags=True,
        artist_from="tag",
    ),
    GdlSiteConfig(
        domain="kemono.cr",
        source_id="kemono",
        name="Kemono",
        category="gallery",
        has_tags=True,
        subscribe_id_key="id",
        subscribe_url_tpl="https://kemono.cr/{}/",
        subscribe_id_pattern=r"/(\w+)/user/(\d+)",
        subscribe_id_format="{1}:{2}",
        retries=5,
        http_timeout=60,
    ),
    GdlSiteConfig(
        domain="mangadex.org",
        source_id="mangadex",
        name="MangaDex",
        category="manga",
        has_tags=True,
    ),
    # ── Filehost ──
    GdlSiteConfig(
        domain="imgur.com",
        source_id="imgur",
        name="Imgur",
        category="filehost",
    ),
    GdlSiteConfig(
        domain="bunkr.si",
        source_id="bunkr",
        name="Bunkr",
        category="filehost",
    ),
    GdlSiteConfig(
        domain="cyberdrop.me",
        source_id="cyberdrop",
        name="Cyberdrop",
        category="filehost",
    ),
    GdlSiteConfig(
        domain="catbox.moe",
        source_id="catbox",
        name="Catbox",
        category="filehost",
    ),
)
