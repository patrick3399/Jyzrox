"""Unified gallery-dl site configuration registry.

Single source of truth for all gallery-dl supported sites.
Replaces scattered config in source.py, _subscribe.py, _metadata.py, and importer.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class GdlSiteConfig:
    """Complete configuration for a gallery-dl supported site."""

    # ── Identity (replaces SiteInfo in source.py) ──
    domain: str
    source_id: str
    name: str
    category: str  # social, booru, art, gallery, manga, filehost
    has_tags: bool = False

    # ── Display (new: per-source cover + ordering) ──
    image_order: Literal["asc", "desc"] = "asc"
    cover_page: Literal["first", "last"] = "first"
    title_fields: tuple[str, ...] = ("title", "title_en")

    # ── Artist extraction strategy (replaces if/elif chains) ──
    artist_from: Literal["uploader", "tag", "twitter_author", "none"] = "uploader"

    # ── Subscription (replaces SITE_CONFIG in _subscribe.py) ──
    subscribe_id_key: str | None = None
    subscribe_url_tpl: str | None = None

    # ── gallery-dl extractor name (replaces _source_to_extractor) ──
    extractor: str | None = None  # None = same as source_id


GDL_SITES: tuple[GdlSiteConfig, ...] = (
    # ── Social ──
    GdlSiteConfig(
        domain="twitter.com", source_id="twitter", name="Twitter/X",
        category="social", has_tags=True,
        image_order="desc", cover_page="last", title_fields=("username",),
        artist_from="twitter_author",
        subscribe_id_key="tweet_id",
        subscribe_url_tpl="https://x.com/{}/media",
    ),
    GdlSiteConfig(
        domain="x.com", source_id="twitter", name="Twitter/X",
        category="social", has_tags=True,
        image_order="desc", cover_page="last", title_fields=("username",),
        artist_from="twitter_author",
        subscribe_id_key="tweet_id",
        subscribe_url_tpl="https://x.com/{}/media",
    ),
    GdlSiteConfig(
        domain="instagram.com", source_id="instagram", name="Instagram",
        category="social", has_tags=True,
        subscribe_id_key="shortcode",
        subscribe_url_tpl="https://www.instagram.com/{}/",
    ),
    GdlSiteConfig(
        domain="facebook.com", source_id="facebook", name="Facebook",
        category="social",
        subscribe_id_key="post_id",
        subscribe_url_tpl="https://www.facebook.com/{}/photos",
    ),
    GdlSiteConfig(
        domain="bsky.app", source_id="bluesky", name="Bluesky",
        category="social", has_tags=True,
        subscribe_id_key="post_id",
        subscribe_url_tpl="https://bsky.app/profile/{}/",
    ),
    GdlSiteConfig(
        domain="tumblr.com", source_id="tumblr", name="Tumblr",
        category="social", has_tags=True,
        subscribe_id_key="id",
        subscribe_url_tpl="https://www.tumblr.com/{}/",
    ),
    GdlSiteConfig(
        domain="reddit.com", source_id="reddit", name="Reddit",
        category="social", has_tags=True,
        subscribe_id_key="id",
        subscribe_url_tpl="https://www.reddit.com/user/{}/submitted/",
    ),

    # ── Booru ──
    GdlSiteConfig(
        domain="danbooru.donmai.us", source_id="danbooru", name="Danbooru",
        category="booru", has_tags=True, artist_from="tag",
    ),
    GdlSiteConfig(
        domain="gelbooru.com", source_id="gelbooru", name="Gelbooru",
        category="booru", has_tags=True, artist_from="tag",
    ),
    GdlSiteConfig(
        domain="e621.net", source_id="e621", name="e621",
        category="booru", has_tags=True, artist_from="tag",
    ),
    GdlSiteConfig(
        domain="yande.re", source_id="yandere", name="Yande.re",
        category="booru", has_tags=True, artist_from="tag",
    ),
    GdlSiteConfig(
        domain="konachan.com", source_id="konachan", name="Konachan",
        category="booru", has_tags=True, artist_from="tag",
    ),
    GdlSiteConfig(
        domain="rule34.xxx", source_id="rule34", name="Rule34",
        category="booru", has_tags=True, artist_from="tag",
    ),
    GdlSiteConfig(
        domain="safebooru.org", source_id="safebooru", name="Safebooru",
        category="booru", has_tags=True, artist_from="tag",
    ),
    GdlSiteConfig(
        domain="sankakucomplex.com", source_id="sankaku", name="Sankaku",
        category="booru", has_tags=True, artist_from="tag",
        extractor="sankakucomplex",
    ),

    # ── Art ──
    GdlSiteConfig(
        domain="deviantart.com", source_id="deviantart", name="DeviantArt",
        category="art", has_tags=True,
        subscribe_id_key="deviationid",
        subscribe_url_tpl="https://www.deviantart.com/{}/gallery/all",
    ),
    GdlSiteConfig(
        domain="artstation.com", source_id="artstation", name="ArtStation",
        category="art", has_tags=True,
    ),
    GdlSiteConfig(
        domain="newgrounds.com", source_id="newgrounds", name="Newgrounds",
        category="art", has_tags=True,
    ),
    GdlSiteConfig(
        domain="inkbunny.net", source_id="inkbunny", name="Inkbunny",
        category="art", has_tags=True,
    ),
    GdlSiteConfig(
        domain="furaffinity.net", source_id="furaffinity", name="Fur Affinity",
        category="art", has_tags=True,
    ),
    GdlSiteConfig(
        domain="civitai.com", source_id="civitai", name="Civitai",
        category="art", has_tags=True,
    ),

    # ── Gallery ──
    GdlSiteConfig(
        domain="nhentai.net", source_id="nhentai", name="nhentai",
        category="gallery", has_tags=True, artist_from="tag",
    ),
    GdlSiteConfig(
        domain="hitomi.la", source_id="hitomi", name="Hitomi.la",
        category="gallery", has_tags=True, artist_from="tag",
    ),
    GdlSiteConfig(
        domain="kemono.su", source_id="kemono", name="Kemono",
        category="gallery", has_tags=True,
        subscribe_id_key="id",
        subscribe_url_tpl="https://kemono.su/{}/",
    ),
    GdlSiteConfig(
        domain="mangadex.org", source_id="mangadex", name="MangaDex",
        category="manga", has_tags=True,
    ),

    # ── Filehost ──
    GdlSiteConfig(
        domain="imgur.com", source_id="imgur", name="Imgur",
        category="filehost",
    ),
    GdlSiteConfig(
        domain="bunkr.si", source_id="bunkr", name="Bunkr",
        category="filehost",
    ),
    GdlSiteConfig(
        domain="cyberdrop.me", source_id="cyberdrop", name="Cyberdrop",
        category="filehost",
    ),
    GdlSiteConfig(
        domain="catbox.moe", source_id="catbox", name="Catbox",
        category="filehost",
    ),
)

# ── Lookup helpers ──

_BY_SOURCE: dict[str, GdlSiteConfig] = {}
_BY_DOMAIN: dict[str, GdlSiteConfig] = {}
for _s in GDL_SITES:
    _BY_SOURCE.setdefault(_s.source_id, _s)  # first entry wins (twitter.com before x.com)
    _BY_DOMAIN[_s.domain] = _s


def get_site_config(source: str) -> GdlSiteConfig | None:
    """Look up site config by source_id."""
    return _BY_SOURCE.get(source)


def get_site_by_domain(domain: str) -> GdlSiteConfig | None:
    """Look up site config by domain."""
    return _BY_DOMAIN.get(domain)
