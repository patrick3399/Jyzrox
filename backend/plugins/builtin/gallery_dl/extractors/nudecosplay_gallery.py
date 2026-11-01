"""Extractor for https://nudecosplay.biz/ (WordPress, JNews theme).

Parsing uses the standard library only. Two gallery-dl installations import
this file (the image's copy and the upgradable venv), so the only gallery-dl
surface it relies on is ``GalleryExtractor`` and ``exception.NotFoundError``.
"""

import html
import json
import re
import unicodedata
from datetime import datetime
from urllib.parse import quote, unquote

from gallery_dl import exception
from gallery_dl.extractor.common import GalleryExtractor

# Read by Jyzrox only (plugins.builtin.gallery_dl._sites): registers the site
# without an entry in GDL_SITES. source_id defaults to the category below.
JYZROX_SITE = {
    "domain": "nudecosplay.biz",
    "name": "NudeCosplay",
    # Title and tags come from the metadata only for gallery/manga sites.
    "category": "gallery",
    "has_tags": True,
    "artist_fields": ("artist",),
    "source_id_fields": ("gallery_id",),
}

_IMG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_SRC_RE = re.compile(r'\s(data-src|src)="([^"]+)"', re.IGNORECASE)
# Titles read "Cosplayer – Character Outfit (Series)"; older ones use a hyphen.
_TITLE_SEP_RE = re.compile(r"\s[–—]\s|\s-\s")
_TRAILING_PARENS_RE = re.compile(r"\s*\(([^()]*)\)\s*$")
# The series may be followed by a set number: "Cinderella (NIKKE) Set 2".
_LAST_PARENS_RE = re.compile(r"\s*\(([^()]*)\)(?!.*\()")
# Edit notes such as "(Update: Added Pics + Video)" are not the series.
_UPDATE_NOTE_RE = re.compile(r"\s*\(\s*update\b[^()]*\)", re.IGNORECASE)
_PUNCT_RE = re.compile(r"[^\w\s]")
_SPACE_RE = re.compile(r"\s+")


def _key(text: str) -> str:
    """Comparison key: punctuation, case, width and spacing differences dropped.

    Tags and titles spell the same name differently ("Kal'tsit" / "Kal’tsit",
    "DVA" / "D.Va", "Ms Hina" / "Ms. Hina", non-breaking spaces).
    """
    text = unicodedata.normalize("NFKC", html.unescape(text))
    return _SPACE_RE.sub(" ", _PUNCT_RE.sub("", text)).strip().casefold()


def _split_parens(text: str) -> tuple[str, str]:
    """``"Lucy (Cyberpunk)"`` -> ``("Lucy", "Cyberpunk")``; no parentheses -> ``(text, "")``."""
    match = _TRAILING_PARENS_RE.search(text)
    if not match:
        return text, ""
    return text[: match.start()], match.group(1)


def _split_series(text: str) -> tuple[str, str]:
    """``"Eve Lingerie (Stellar Blade) Set 2"`` -> ``("Eve Lingerie Set 2", "Stellar Blade")``."""
    match = _LAST_PARENS_RE.search(text)
    if not match:
        return text, ""
    return text[: match.start()] + text[match.end() :], match.group(1)


def _contains(haystack: str, needle: str) -> bool:
    """Whole-word containment of one comparison key in another."""
    return bool(needle) and f" {needle} " in f" {haystack} "


def _is_character(tag: str, character_key: str, series_key: str) -> bool:
    """A qualified tag ("Lucy (Cyberpunk)") names the character by its base name.

    The qualifier must not contradict the title's series, so "Jessie (Pokemon)"
    is not the character of "Jessie (Toy Story)".
    """
    base, qualifier = _split_parens(tag)
    if not qualifier or not _contains(character_key, _key(base)):
        return False
    qualifier_key = _key(qualifier)
    return not series_key or _contains(series_key, qualifier_key) or _contains(qualifier_key, series_key)


def _classify_tags(title: str, tags: list[str]) -> dict[str, list[str]]:
    """Sort a post's tags into artist / character / parody / general.

    A post is tagged with its cosplayer, character and series, and the title
    names the cosplayer before the dash and the character (plus outfit, plus
    the series in parentheses) after it. A tag is only placed where the title
    confirms it, except that when the title names no series, a single
    leftover tag next to a confirmed cosplayer and character is the series.
    Anything else stays general.
    """
    title = _UPDATE_NOTE_RE.sub("", html.unescape(title)).strip()
    parts = _TITLE_SEP_RE.split(title, maxsplit=1)
    if len(parts) == 2:
        left, right = parts
    else:
        left, right = "", title
    # "A & B" is a collab; "Name (Alias)" names the cosplayer twice.
    cosplayers = set()
    for name in re.split(r"\s*&\s*|\s*,\s*", left):
        base, alias = _split_parens(name)
        cosplayers.update(k for k in (_key(base), _key(alias)) if k)
    character_part, series = _split_series(right)
    character_key = _key(character_part)
    series_key = _key(series)

    groups: dict[str, list[str]] = {"artist": [], "character": [], "parody": [], "general": []}
    leftovers = []
    for name in tags:
        key = _key(name)
        if not key:
            continue
        if key in cosplayers:
            groups["artist"].append(name)
        elif series_key and key == series_key:
            groups["parody"].append(name)
        elif _contains(character_key, key) or _is_character(name, character_key, series_key):
            groups["character"].append(name)
        else:
            leftovers.append(name)
    # A title that names its series but matched no tag confirms nothing.
    if len(leftovers) == 1 and groups["artist"] and groups["character"] and not series_key:
        groups["parody"] = leftovers
    else:
        groups["general"] = leftovers
    return groups


def _post_metadata(post: dict) -> dict:
    """Gallery-level metadata from a WordPress REST post object."""
    terms = [term for group in post.get("_embedded", {}).get("wp:term", ()) for term in group]

    def names(taxonomy: str) -> list[str]:
        seen: set[str] = set()
        result = []
        for term in terms:
            if term.get("taxonomy") != taxonomy:
                continue
            name = html.unescape(term["name"]).strip()
            if name and name.casefold() not in seen:
                seen.add(name.casefold())
                result.append(name)
        return result

    title = html.unescape(post["title"]["rendered"]).strip()
    groups = _classify_tags(title, names("post_tag"))
    # Categories are site sections ("Ero Cosplay", "Nude", "Online Video").
    seen = {name.casefold() for group in groups.values() for name in group}
    groups["general"] += [name for name in names("category") if name.casefold() not in seen]

    tags = {namespace: values for namespace, values in groups.items() if values}
    artists = groups["artist"]
    return {
        "gallery_id": unquote(post["slug"]),
        "id": post["id"],
        "title": title,
        "date": datetime.fromisoformat(post["date_gmt"]),
        "tags": tags,
        "artist": artists[0] if artists else "",
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


class NudecosplayGalleryExtractor(GalleryExtractor):
    """Extractor for a single nudecosplay.biz post"""

    category = "nudecosplay"
    root = "https://nudecosplay.biz"
    # A post is a single path segment; listings (/category/x/, /tag/x/,
    # /page/2/) have two, and the reserved single-segment pages are excluded.
    pattern = (
        r"(?:https?://)?(?:www\.)?nudecosplay\.biz/"
        r"(?!(?:category|tag|author|page|feed|search|most-popular|popular-this-month"
        r"|popular-this-week|wp-[^/?#]*)/?(?:[?#]|$))"
        r"([^/?#.]+)/?(?:[?#]|$)"
    )
    example = "https://nudecosplay.biz/cosplayer-character-series/"
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
        return _post_metadata(self.post)

    def images(self, page):
        return [(url, None) for url in _image_urls(self.post["content"]["rendered"])]
