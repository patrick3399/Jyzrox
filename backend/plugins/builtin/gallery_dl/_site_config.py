"""GdlSiteConfig dataclass for gallery-dl supported sites."""

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
    artist_from: Literal["uploader", "tag", "twitter_author", "pixiv_user", "none"] = "uploader"
    # Dotted metadata paths tried in order for the artist key; when set they
    # take precedence over ``artist_from``.
    artist_fields: tuple[str, ...] = ()

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
    retries: int = 4  # gallery-dl default
    http_timeout: int = 30  # seconds
    sleep_request: float | tuple[float, float] | None = None  # seconds between API/page requests
    sleep_download: float | tuple[float, float] | None = None  # seconds between file downloads
    inactivity_timeout: int = 300  # seconds before killing process on no output

    # ── URL parsing ──
    # Index of the path segment used as source_id in ensure_gallery_from_url.
    # E.g. weibo.com/u/USERID has the ID at index 1 (skip the "u" prefix).
    url_path_id_index: int = 0

    # ── URL identity (ADR 0016) ──
    # gallery-dl subcategories that are views of one account; they all map to
    # the bare account name taken from match group ``account_group``.
    account_subcategories: tuple[str, ...] = ()
    account_group: int = 0
