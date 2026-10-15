"""Extractor for http://www.xiuren7.com/ (WordPress, zibll theme).

Parsing uses the standard library only. Two gallery-dl installations import
this file (the image's copy and the upgradable venv), so the only gallery-dl
surface it relies on is the ``GalleryExtractor`` base class.
"""

import html
import json
import re
from datetime import datetime

from gallery_dl.extractor.common import GalleryExtractor

# Read by Jyzrox only (plugins.builtin.gallery_dl._sites): registers the site
# without an entry in GDL_SITES. source_id defaults to the category below.
JYZROX_SITE = {
    "domain": "xiuren7.com",
    "name": "XiuRen7",
    # Title and tags come from the metadata only for gallery/manga sites.
    "category": "gallery",
    "has_tags": True,
    # Every post carries the model's name as its only tag; _post_metadata
    # copies it to "artist".
    "artist_fields": ("artist",),
    "source_id_fields": ("gallery_id",),
}

_IMG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_SRC_RE = re.compile(r'\s(data-src|src)="([^"]+)"', re.IGNORECASE)


def _post_metadata(post: dict) -> dict:
    """Gallery-level metadata from a WordPress REST post object."""
    terms = [term for group in post.get("_embedded", {}).get("wp:term", ()) for term in group]
    # Every post carries the model/performer name as its only post_tag.
    tags = [html.unescape(term["name"]) for term in terms if term.get("taxonomy") == "post_tag"]
    return {
        "gallery_id": post["id"],
        "title": html.unescape(post["title"]["rendered"]).strip(),
        "date": datetime.fromisoformat(post["date_gmt"]),
        "tags": tags,
        "artist": tags[0] if tags else "",
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
        urls.append("http:" + url if url.startswith("//") else url)
    return urls


class Xiuren7GalleryExtractor(GalleryExtractor):
    """Extractor for a single xiuren7.com post"""

    category = "xiuren7"
    # HTTPS serves a self-signed certificate; the site links to itself over HTTP.
    root = "http://www.xiuren7.com"
    pattern = r"(?:https?://)?(?:www\.)?xiuren7\.com/(\d+)\.html"
    example = "http://www.xiuren7.com/12345.html"
    directory_fmt = ("{category}", "{gallery_id} {title}")
    filename_fmt = "{num:>03}.{extension}"
    # Starts with the URL identity Jyzrox keys the gallery by (ADR 0016), so
    # archive entries link to their gallery by prefix instead of by the
    # "written while this job ran" window, which mixes up overlapping downloads.
    archive_fmt = "gallery={gallery_id}_{num}"

    def __init__(self, match):
        # The post is public through the WordPress REST API, which returns the
        # whole image list in one response; the HTML page adds only theme chrome.
        url = f"{self.root}/wp-json/wp/v2/posts/{match.group(1)}?_embed=wp:term"
        GalleryExtractor.__init__(self, match, url)

    def metadata(self, page):
        self.post = json.loads(page)
        return _post_metadata(self.post)

    def images(self, page):
        return [(url, None) for url in _image_urls(self.post["content"]["rendered"])]
