"""Shared utility functions used across routers and workers."""

import urllib.parse

SITE_REGISTRY: list[dict] = [
    {"domain": "pixiv.net", "source_id": "pixiv", "name": "Pixiv", "category": "art", "has_tags": True},
    {"domain": "e-hentai.org", "source_id": "ehentai", "name": "E-Hentai", "category": "gallery", "has_tags": True},
    {"domain": "exhentai.org", "source_id": "ehentai", "name": "ExHentai", "category": "gallery", "has_tags": True},
    {"domain": "twitter.com", "source_id": "twitter", "name": "Twitter/X", "category": "social", "has_tags": True},
    {"domain": "x.com", "source_id": "twitter", "name": "Twitter/X", "category": "social", "has_tags": True},
    {"domain": "danbooru.donmai.us", "source_id": "danbooru", "name": "Danbooru", "category": "booru", "has_tags": True},
    {"domain": "gelbooru.com", "source_id": "gelbooru", "name": "Gelbooru", "category": "booru", "has_tags": True},
    {"domain": "e621.net", "source_id": "e621", "name": "e621", "category": "booru", "has_tags": True},
    {"domain": "yande.re", "source_id": "yandere", "name": "Yande.re", "category": "booru", "has_tags": True},
    {"domain": "konachan.com", "source_id": "konachan", "name": "Konachan", "category": "booru", "has_tags": True},
    {"domain": "rule34.xxx", "source_id": "rule34", "name": "Rule34", "category": "booru", "has_tags": True},
    {"domain": "safebooru.org", "source_id": "safebooru", "name": "Safebooru", "category": "booru", "has_tags": True},
    {"domain": "sankakucomplex.com", "source_id": "sankaku", "name": "Sankaku", "category": "booru", "has_tags": True},
    {"domain": "deviantart.com", "source_id": "deviantart", "name": "DeviantArt", "category": "art", "has_tags": True},
    {"domain": "artstation.com", "source_id": "artstation", "name": "ArtStation", "category": "art", "has_tags": True},
    {"domain": "newgrounds.com", "source_id": "newgrounds", "name": "Newgrounds", "category": "art", "has_tags": True},
    {"domain": "inkbunny.net", "source_id": "inkbunny", "name": "Inkbunny", "category": "art", "has_tags": True},
    {"domain": "furaffinity.net", "source_id": "furaffinity", "name": "Fur Affinity", "category": "art", "has_tags": True},
    {"domain": "nhentai.net", "source_id": "nhentai", "name": "nhentai", "category": "gallery", "has_tags": True},
    {"domain": "hitomi.la", "source_id": "hitomi", "name": "Hitomi.la", "category": "gallery", "has_tags": True},
    {"domain": "kemono.su", "source_id": "kemono", "name": "Kemono", "category": "gallery", "has_tags": True},
    {"domain": "mangadex.org", "source_id": "mangadex", "name": "MangaDex", "category": "manga", "has_tags": True},
    {"domain": "instagram.com", "source_id": "instagram", "name": "Instagram", "category": "social", "has_tags": True},
    {"domain": "bsky.app", "source_id": "bluesky", "name": "Bluesky", "category": "social", "has_tags": True},
    {"domain": "tumblr.com", "source_id": "tumblr", "name": "Tumblr", "category": "social", "has_tags": True},
    {"domain": "reddit.com", "source_id": "reddit", "name": "Reddit", "category": "social", "has_tags": True},
    {"domain": "facebook.com", "source_id": "facebook", "name": "Facebook", "category": "social", "has_tags": False},
    # AI / Models
    {"domain": "civitai.com", "source_id": "civitai", "name": "Civitai", "category": "art", "has_tags": True},
    {"domain": "imgur.com", "source_id": "imgur", "name": "Imgur", "category": "filehost", "has_tags": False},
    {"domain": "bunkr.si", "source_id": "bunkr", "name": "Bunkr", "category": "filehost", "has_tags": False},
    {"domain": "cyberdrop.me", "source_id": "cyberdrop", "name": "Cyberdrop", "category": "filehost", "has_tags": False},
    {"domain": "catbox.moe", "source_id": "catbox", "name": "Catbox", "category": "filehost", "has_tags": False},
]


def detect_source(url: str) -> str:
    """Auto-detect download source from URL domain."""
    entry = detect_source_info(url)
    if entry is not None:
        return entry["source_id"]
    return "unknown"


def detect_source_info(url: str) -> dict | None:
    """Return the full SITE_REGISTRY entry for the given URL, or None if not matched."""
    try:
        parsed = urllib.parse.urlparse(url)
        netloc = parsed.netloc.lower()
    except Exception:
        return None

    if not netloc:
        return None

    for entry in SITE_REGISTRY:
        domain = entry["domain"]
        # Match exact domain or any subdomain (e.g. "www.pixiv.net")
        if netloc == domain or netloc.endswith("." + domain):
            return entry

    return None


def get_supported_sites() -> dict[str, list[dict]]:
    """Return SITE_REGISTRY entries grouped by category, deduplicated by source_id."""
    categories: dict[str, list[dict]] = {}
    seen: set[str] = set()
    for entry in SITE_REGISTRY:
        sid = entry["source_id"]
        if sid in seen:
            continue
        seen.add(sid)
        cat = entry["category"]
        categories.setdefault(cat, []).append(entry)
    return categories
