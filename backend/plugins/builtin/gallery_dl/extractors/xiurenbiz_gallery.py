"""Extractor for https://xiuren.biz/ (WordPress, JNews theme).

Parsing uses the standard library only. Two gallery-dl installations import
this file (the image's copy and the upgradable venv), so the only gallery-dl
surface it relies on is ``GalleryExtractor`` and ``exception.NotFoundError``.
"""

import html
import json
import re
from datetime import datetime
from urllib.parse import quote, unquote

from gallery_dl import exception
from gallery_dl.extractor.common import GalleryExtractor

# Read by Jyzrox only (plugins.builtin.gallery_dl._sites): registers the site
# without an entry in GDL_SITES. source_id defaults to the category below.
JYZROX_SITE = {
    "domain": "xiuren.biz",
    "name": "XiuRen.biz",
    # Title and tags come from the metadata only for gallery/manga sites.
    "category": "gallery",
    "has_tags": True,
    "artist_fields": ("artist",),
    "source_id_fields": ("gallery_id",),
}

_IMG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_SRC_RE = re.compile(r'\s(data-src|src)="([^"]+)"', re.IGNORECASE)


def _category_keys(categories: list[dict]) -> set[str]:
    """Casefolded names and slugs of the site's categories (the studio labels)."""
    keys = set()
    for category in categories:
        keys.add(html.unescape(category.get("name", "")).casefold())
        keys.add(unquote(category.get("slug", "")).casefold())
    keys.discard("")
    return keys


def _post_metadata(post: dict, category_keys: set[str]) -> dict:
    """Gallery-level metadata from a WordPress REST post object.

    Posts tag the model together with studio labels ("Xiuren", "XiuRen Extra")
    that are also site categories; a tag that is not a category name is a model.
    """
    terms = [term for group in post.get("_embedded", {}).get("wp:term", ()) for term in group]
    models: list[str] = []
    general: list[str] = []
    seen: set[str] = set()
    # Tags before categories, so a studio tag keeps the tag's own spelling.
    for taxonomy in ("post_tag", "category"):
        for term in terms:
            if term.get("taxonomy") != taxonomy:
                continue
            name = html.unescape(term["name"]).strip()
            key = name.casefold()
            if not name or key in seen:
                continue
            seen.add(key)
            is_studio = key in category_keys or unquote(term.get("slug", "")).casefold() in category_keys
            if taxonomy == "post_tag" and not is_studio:
                models.append(name)
            else:
                general.append(name)

    tags = {}
    if models:
        tags["artist"] = models
    if general:
        tags["general"] = general
    return {
        "gallery_id": unquote(post["slug"]),
        "id": post["id"],
        "title": html.unescape(post["title"]["rendered"]).strip(),
        "date": datetime.fromisoformat(post["date_gmt"]),
        "tags": tags,
        "artist": models[0] if models else "",
    }


def _image_urls(content: str) -> list[str]:
    """Image URLs in document order; a lazy-load ``data-src`` wins over ``src``."""
    urls = []
    for tag in _IMG_RE.findall(content):
        sources = {name.lower(): value for name, value in _SRC_RE.findall(tag)}
        url = sources.get("data-src") or sources.get("src")
        if not url:
            continue
        url = html.unescape(url)
        urls.append("https:" + url if url.startswith("//") else url)
    return urls


class XiurenbizGalleryExtractor(GalleryExtractor):
    """Extractor for a single xiuren.biz post"""

    category = "xiurenbiz"
    root = "https://xiuren.biz"
    # A post is a single path segment; listings (/category/x/, /tag/x/,
    # /page/2/) have two, and the reserved single-segment pages are excluded.
    pattern = (
        r"(?:https?://)?(?:www\.)?xiuren\.biz/"
        r"(?!(?:category|tag|author|page|feed|search|popular-this-month|popular-this-week"
        r"|most_popular|latest-post|wp-[^/?#]*)/?(?:[?#]|$))"
        r"([^/?#.]+)/?(?:[?#]|$)"
    )
    example = "https://xiuren.biz/xiuren-vol-12345-name/"
    directory_fmt = ("{category}", "{gallery_id}")
    filename_fmt = "{num:>03}.{extension}"
    # Starts with the URL identity Jyzrox keys the gallery by (ADR 0016), so
    # archive entries link to their gallery by prefix.
    archive_fmt = "gallery={gallery_id}_{num}"

    def __init__(self, match):
        # Browsers copy the slug with uppercase percent-escapes, the site links
        # with lowercase ones, and WordPress slugs are lowercase. Jyzrox keys
        # the gallery by these groups, so normalise them to the decoded slug.
        slug = unquote(match.group(1)).lower()
        url = f"{self.root}/wp-json/wp/v2/posts?slug={quote(slug)}&_embed=wp:term"
        GalleryExtractor.__init__(self, match, url)
        self.groups = (slug,)

    def metadata(self, page):
        posts = json.loads(page)
        if not posts:
            raise exception.NotFoundError("post")
        self.post = posts[0]
        categories = self.request(f"{self.root}/wp-json/wp/v2/categories?per_page=100&_fields=name,slug").json()
        return _post_metadata(self.post, _category_keys(categories))

    def images(self, page):
        return [(url, None) for url in _image_urls(self.post["content"]["rendered"])]
