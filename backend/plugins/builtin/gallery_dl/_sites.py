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

    # ── Credential ──
    credential_type: Literal["cookies", "refresh_token", "none"] = "cookies"
    extra_extractors: tuple[str, ...] = ()
    credential_requirement: Literal["required", "recommended", "none"] = "none"
    credential_warning_code: str | None = None

    # ── Metadata ──
    source_id_fields: tuple[str, ...] = ("gallery_id", "id")
    normalize_namespaces: bool = False

    # ── Subscription source_id extraction ──
    subscribe_id_pattern: str | None = None
    subscribe_id_format: str | None = None

    # ── Feature toggle ──
    feature_toggle_key: str | None = None
    feature_toggle_attr: str | None = None

    # ── Artist URL ──
    artist_url_tpl: str | None = None

    # ── Download tuning ──
    retries: int = 4          # gallery-dl default
    http_timeout: int = 30    # seconds
    sleep_request: float | tuple[float, float] | None = None  # seconds between requests


GDL_SITES: tuple[GdlSiteConfig, ...] = (
    # ── EH / Pixiv (added before social/booru so _BY_SOURCE gets ehentai from e-hentai.org first) ──
    GdlSiteConfig(
        domain="e-hentai.org", source_id="ehentai", name="E-Hentai",
        category="gallery", has_tags=True, artist_from="tag",
        credential_type="cookies", extra_extractors=("exhentai", "e-hentai"),
        credential_requirement="recommended",
        credential_warning_code="eh_credentials_recommended",
        feature_toggle_key="setting:download_eh_enabled",
        feature_toggle_attr="download_eh_enabled",
        source_id_fields=("gallery_id",),
        normalize_namespaces=True,
        artist_url_tpl="https://e-hentai.org/tag/artist:{}",
        retries=5, http_timeout=45,
    ),
    GdlSiteConfig(
        domain="exhentai.org", source_id="ehentai", name="ExHentai",
        category="gallery", has_tags=True, artist_from="tag",
        credential_type="cookies", extra_extractors=("exhentai", "e-hentai"),
        credential_requirement="recommended",
        credential_warning_code="eh_credentials_recommended",
        feature_toggle_key="setting:download_eh_enabled",
        feature_toggle_attr="download_eh_enabled",
        source_id_fields=("gallery_id",),
        normalize_namespaces=True,
        artist_url_tpl="https://e-hentai.org/tag/artist:{}",
        retries=5, http_timeout=45,
    ),
    GdlSiteConfig(
        domain="pixiv.net", source_id="pixiv", name="Pixiv",
        category="art", has_tags=True,
        subscribe_id_key="id",
        subscribe_url_tpl="https://www.pixiv.net/users/{}/",
        credential_type="refresh_token",
        credential_requirement="required",
        credential_warning_code="pixiv_credentials_required",
        feature_toggle_key="setting:download_pixiv_enabled",
        feature_toggle_attr="download_pixiv_enabled",
        source_id_fields=("id",),
        subscribe_id_pattern=r"/users/(\d+)",
        artist_url_tpl="https://www.pixiv.net/users/{}",
        retries=5, http_timeout=45,
    ),

    # ── Social ──
    GdlSiteConfig(
        domain="twitter.com", source_id="twitter", name="Twitter/X",
        category="social", has_tags=True,
        image_order="asc", cover_page="first", title_fields=("author.name", "user.name", "username"),
        artist_from="twitter_author",
        subscribe_id_key="tweet_id",
        subscribe_url_tpl="https://x.com/{}/media",
        source_id_fields=("tweet_id",),
        subscribe_id_pattern=r"^/([^/]+)",
        artist_url_tpl="https://x.com/{}",
    ),
    GdlSiteConfig(
        domain="x.com", source_id="twitter", name="Twitter/X",
        category="social", has_tags=True,
        image_order="asc", cover_page="first", title_fields=("author.name", "user.name", "username"),
        artist_from="twitter_author",
        subscribe_id_key="tweet_id",
        subscribe_url_tpl="https://x.com/{}/media",
        source_id_fields=("tweet_id",),
        subscribe_id_pattern=r"^/([^/]+)",
        artist_url_tpl="https://x.com/{}",
    ),
    GdlSiteConfig(
        domain="instagram.com", source_id="instagram", name="Instagram",
        category="social", has_tags=True,
        subscribe_id_key="shortcode",
        subscribe_url_tpl="https://www.instagram.com/{}/",
        subscribe_id_pattern=r"^/(@?[^/]+)",
    ),
    GdlSiteConfig(
        domain="facebook.com", source_id="facebook", name="Facebook",
        category="social",
        subscribe_id_key="post_id",
        subscribe_url_tpl="https://www.facebook.com/{}/photos",
        subscribe_id_pattern=r"^/([^/]+)",
        credential_requirement="recommended",
        sleep_request=(2.0, 4.0),
        retries=5, http_timeout=45,
    ),
    GdlSiteConfig(
        domain="bsky.app", source_id="bluesky", name="Bluesky",
        category="social", has_tags=True,
        subscribe_id_key="post_id",
        subscribe_url_tpl="https://bsky.app/profile/{}/",
        subscribe_id_pattern=r"^/([^/]+)",
    ),
    GdlSiteConfig(
        domain="tumblr.com", source_id="tumblr", name="Tumblr",
        category="social", has_tags=True,
        subscribe_id_key="id",
        subscribe_url_tpl="https://www.tumblr.com/{}/",
        subscribe_id_pattern=r"^/([^/]+)",
    ),
    GdlSiteConfig(
        domain="reddit.com", source_id="reddit", name="Reddit",
        category="social", has_tags=True,
        subscribe_id_key="id",
        subscribe_url_tpl="https://www.reddit.com/user/{}/submitted/",
        subscribe_id_pattern=r"^/([^/]+)",
    ),

    # ── Booru ──
    GdlSiteConfig(
        domain="danbooru.donmai.us", source_id="danbooru", name="Danbooru",
        category="booru", has_tags=True, artist_from="tag",
        normalize_namespaces=True,
    ),
    GdlSiteConfig(
        domain="gelbooru.com", source_id="gelbooru", name="Gelbooru",
        category="booru", has_tags=True, artist_from="tag",
        normalize_namespaces=True,
    ),
    GdlSiteConfig(
        domain="e621.net", source_id="e621", name="e621",
        category="booru", has_tags=True, artist_from="tag",
        normalize_namespaces=True,
    ),
    GdlSiteConfig(
        domain="yande.re", source_id="yandere", name="Yande.re",
        category="booru", has_tags=True, artist_from="tag",
        normalize_namespaces=True,
    ),
    GdlSiteConfig(
        domain="konachan.com", source_id="konachan", name="Konachan",
        category="booru", has_tags=True, artist_from="tag",
        normalize_namespaces=True,
    ),
    GdlSiteConfig(
        domain="rule34.xxx", source_id="rule34", name="Rule34",
        category="booru", has_tags=True, artist_from="tag",
        normalize_namespaces=True,
    ),
    GdlSiteConfig(
        domain="safebooru.org", source_id="safebooru", name="Safebooru",
        category="booru", has_tags=True, artist_from="tag",
        normalize_namespaces=True,
    ),
    GdlSiteConfig(
        domain="sankakucomplex.com", source_id="sankaku", name="Sankaku",
        category="booru", has_tags=True, artist_from="tag",
        extractor="sankakucomplex",
        normalize_namespaces=True,
    ),

    # ── Art ──
    GdlSiteConfig(
        domain="deviantart.com", source_id="deviantart", name="DeviantArt",
        category="art", has_tags=True,
        subscribe_id_key="deviationid",
        subscribe_url_tpl="https://www.deviantart.com/{}/gallery/all",
        subscribe_id_pattern=r"^/([^/]+)",
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
        subscribe_id_pattern=r"/(\w+)/user/(\d+)",
        subscribe_id_format="{1}:{2}",
        retries=5, http_timeout=60,
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
    _BY_SOURCE.setdefault(_s.source_id, _s)  # first entry wins (e-hentai.org before exhentai.org)
    _BY_DOMAIN[_s.domain] = _s

_DEFAULT_CONFIG = GdlSiteConfig(
    domain="", source_id="gallery_dl", name="Unknown Site", category="other",
)

_ALIASES: dict[str, str] = {"exhentai": "ehentai"}


def get_site_config(source: str) -> GdlSiteConfig:
    """Look up site config by source_id. Unknown sites → _DEFAULT_CONFIG."""
    resolved = _ALIASES.get(source, source)
    return _BY_SOURCE.get(resolved, _DEFAULT_CONFIG)


def get_site_by_domain(domain: str) -> GdlSiteConfig:
    """Look up site config by domain. Unknown domains → _DEFAULT_CONFIG."""
    return _BY_DOMAIN.get(domain, _DEFAULT_CONFIG)
