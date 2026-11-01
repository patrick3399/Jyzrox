"""Tests for the bundled nudecosplay.biz gallery-dl extractor and its Jyzrox wiring."""

import importlib.util
import json
import re
import sys
import types
from datetime import UTC, datetime
from pathlib import Path

import pytest

_EXTRACTOR_DIR = Path(__file__).resolve().parent.parent / "plugins" / "builtin" / "gallery_dl" / "extractors"

_SLUG = "walkure-絞肉姬-kaltsit"

_POST = {
    "id": 944160,
    "slug": "walkure-%e7%b5%9e%e8%82%89%e5%a7%ac-kaltsit",
    "date_gmt": "2026-09-21T19:40:28",
    "title": {"rendered": " Walküre 絞肉姬 &#8211; Kal&#8217;tsit "},
    "content": {
        "rendered": (
            '<p><a href="https://nudecosplay.biz/wp-content/uploads/2026/09/Cover.jpg">'
            '<img loading="lazy" src="https://nudecosplay.biz/wp-content/uploads/2026/09/Cover.jpg" /></a><br />\n'
            '<img src="https://nudecosplay.biz/lazy.svg" data-src="//nudecosplay.biz/wp-content/uploads/2026/09/1.jpg?x=1&amp;y=2" />\n'
            '<img alt="no source" />\n'
            '<IMG SRC="https://nudecosplay.biz/wp-content/uploads/2026/09/2.webp"></p>'
        )
    },
    "_embedded": {
        "wp:term": [
            [
                {"taxonomy": "category", "name": "Ero Cosplay", "slug": "ero-cosplay"},
                {"taxonomy": "category", "name": "Nude", "slug": "nude"},
            ],
            [
                {"taxonomy": "post_tag", "name": "Arknights", "slug": "arknights"},
                {"taxonomy": "post_tag", "name": "Kal'tsit", "slug": "kaltsit"},
                {"taxonomy": "post_tag", "name": "Walküre 絞肉姬", "slug": "walkure-%e7%b5%9e%e8%82%89%e5%a7%ac"},
            ],
        ]
    },
}


class _NotFoundError(Exception):
    pass


@pytest.fixture
def nudecosplay(monkeypatch):
    """Import the extractor module against a stub of the gallery-dl surface it uses."""

    class _GalleryExtractor:
        def __init__(self, match, url=None):
            self.groups = match.groups()
            self.page_url = url

    package = types.ModuleType("gallery_dl")
    extractor = types.ModuleType("gallery_dl.extractor")
    common = types.ModuleType("gallery_dl.extractor.common")
    exception = types.ModuleType("gallery_dl.exception")
    common.GalleryExtractor = _GalleryExtractor
    exception.NotFoundError = _NotFoundError
    package.extractor = extractor
    package.exception = exception
    extractor.common = common
    monkeypatch.setitem(sys.modules, "gallery_dl", package)
    monkeypatch.setitem(sys.modules, "gallery_dl.extractor", extractor)
    monkeypatch.setitem(sys.modules, "gallery_dl.extractor.common", common)
    monkeypatch.setitem(sys.modules, "gallery_dl.exception", exception)

    spec = importlib.util.spec_from_file_location(
        "nudecosplay_gallery_under_test", _EXTRACTOR_DIR / "nudecosplay_gallery.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def nudecosplay_site(nudecosplay, monkeypatch):
    """Register the module's JYZROX_SITE the way load_inprocess() does, in an isolated registry."""
    from plugins.builtin.gallery_dl import _sites

    monkeypatch.setattr(_sites, "_BY_SOURCE", dict(_sites._BY_SOURCE))
    monkeypatch.setattr(_sites, "_BY_DOMAIN", dict(_sites._BY_DOMAIN))
    monkeypatch.setattr(_sites, "_EXTRA_SITES", [])
    monkeypatch.setattr(_sites, "_EXTRA_METADATA_FIELDS", [])
    config, fields = _sites.site_config_from_declaration(
        nudecosplay.JYZROX_SITE, {nudecosplay.NudecosplayGalleryExtractor.category}
    )
    assert _sites.register_site(config, fields) is None
    return config


def _extractor(module, url):
    cls = module.NudecosplayGalleryExtractor
    return cls(re.match(cls.pattern, url))


# ── URL matching ──


@pytest.mark.parametrize(
    "url",
    [
        "https://nudecosplay.biz/walkure-%E7%B5%9E%E8%82%89%E5%A7%AC-kaltsit/",
        "https://nudecosplay.biz/walkure-%e7%b5%9e%e8%82%89%e5%a7%ac-kaltsit/",
        "https://nudecosplay.biz/walkure-絞肉姬-kaltsit/",
        "http://www.nudecosplay.biz/plathong-cipher-honkai-star-rail",
        "nudecosplay.biz/umeko-j-hsin-wuthering-waves/?utm_source=x",
        "https://nudecosplay.biz/umeko-j-hsin-wuthering-waves/#comments",
    ],
)
def test_pattern_matches_post_url_in_any_encoding_scheme_or_suffix(nudecosplay, url):
    assert re.match(nudecosplay.NudecosplayGalleryExtractor.pattern, url) is not None


@pytest.mark.parametrize(
    "url",
    [
        "https://nudecosplay.biz/",
        "https://nudecosplay.biz/category/ero-cosplay/",
        "https://nudecosplay.biz/tag/arknights/",
        "https://nudecosplay.biz/page/2/",
        "https://nudecosplay.biz/category/",
        "https://nudecosplay.biz/most-popular/",
        "https://nudecosplay.biz/popular-this-week/",
        "https://nudecosplay.biz/popular-this-month/",
        "https://nudecosplay.biz/xmlrpc.php",
        "https://nudecosplay.biz/wp-json/",
        "https://nudecosplay.biz/umeko-j-hsin-wuthering-waves/2/",
        "https://nudecosplay.biz/wp-content/uploads/2026/09/a.jpg",
        "https://notnudecosplay.biz.example/umeko-j-hsin-wuthering-waves/",
    ],
)
def test_pattern_rejects_listing_pages_files_and_other_hosts(nudecosplay, url):
    assert re.match(nudecosplay.NudecosplayGalleryExtractor.pattern, url) is None


@pytest.mark.parametrize(
    "url",
    [
        "https://nudecosplay.biz/walkure-%E7%B5%9E%E8%82%89%E5%A7%AC-kaltsit/",
        "https://nudecosplay.biz/walkure-%e7%b5%9e%e8%82%89%e5%a7%ac-kaltsit/",
        "https://nudecosplay.biz/walkure-絞肉姬-kaltsit/",
        "https://nudecosplay.biz/Walkure-%E7%B5%9E%E8%82%89%E5%A7%AC-Kaltsit",
    ],
)
def test_identity_groups_are_the_decoded_lowercase_slug_whatever_the_url_encoding(nudecosplay, url):
    """Jyzrox keys the gallery by the match groups (ADR 0016)."""
    assert _extractor(nudecosplay, url).groups == (_SLUG,)


def test_extractor_requests_rest_api_by_slug_not_the_html_page(nudecosplay):
    extractor = _extractor(nudecosplay, "https://nudecosplay.biz/walkure-絞肉姬-kaltsit/")
    assert extractor.page_url == (
        "https://nudecosplay.biz/wp-json/wp/v2/posts?slug=walkure-%E7%B5%9E%E8%82%89%E5%A7%AC-kaltsit&_embed=wp:term"
    )


# ── tag classification ──


@pytest.mark.parametrize(
    ("title", "tags", "expected"),
    [
        # Series in the title.
        (
            "Plathong – Cipher (Honkai: Star Rail)",
            ["Cipher", "Honkai: Star Rail", "Plathong"],
            {"artist": ["Plathong"], "character": ["Cipher"], "parody": ["Honkai: Star Rail"]},
        ),
        # Series only in the tags: the single leftover next to a cosplayer and a character.
        (
            "Kalinka Fox – Sakura Haruno",
            ["Kalinka Fox", "Naruto", "Sakura Haruno"],
            {"artist": ["Kalinka Fox"], "character": ["Sakura Haruno"], "parody": ["Naruto"]},
        ),
        # The character is a prefix of the outfit description.
        (
            "Neppu ネップ – Cinderella Crystal Wave (NIKKE)",
            ["Cinderella", "Neppu ネップ", "NIKKE"],
            {"artist": ["Neppu ネップ"], "character": ["Cinderella"], "parody": ["NIKKE"]},
        ),
        # A set number after the series.
        (
            "Umeko J – Cinderella Crystal Wave (NIKKE) Set 2",
            ["Cinderella", "NIKKE", "Umeko J"],
            {"artist": ["Umeko J"], "character": ["Cinderella"], "parody": ["NIKKE"]},
        ),
        # Punctuation and apostrophe variants between tag and title.
        (
            "Alinorac – D.Va",
            ["Alinorac", "DVA", "Overwatch"],
            {"artist": ["Alinorac"], "character": ["DVA"], "parody": ["Overwatch"]},
        ),
        (
            "Walküre 絞肉姬 – Kal’tsit",
            ["Arknights", "Kal'tsit", "Walküre 絞肉姬"],
            {"artist": ["Walküre 絞肉姬"], "character": ["Kal'tsit"], "parody": ["Arknights"]},
        ),
        # A tag qualified with its series names the character by its base name.
        (
            "Nicky Brum – Lucy (Cyberpunk Edgerunners)",
            ["Cyberpunk Edgerunners", "Lucy (Cyberpunk)", "Nicky Brum"],
            {"artist": ["Nicky Brum"], "character": ["Lucy (Cyberpunk)"], "parody": ["Cyberpunk Edgerunners"]},
        ),
        # The cosplayer's alias in parentheses.
        (
            "Helly von Valentine (Disharmonica) – 2B Wedding Dress",
            ["2B", "Helly von Valentine", "Nier Automata"],
            {"artist": ["Helly von Valentine"], "character": ["2B"], "parody": ["Nier Automata"]},
        ),
        # An edit note in parentheses is not the series.
        (
            "Byoru – Marin Kitagawa (Update: Added Pics + Video)",
            ["Byoru", "Marin Kitagawa", "Sono Bisque Doll wa Koi o Suru"],
            {"artist": ["Byoru"], "character": ["Marin Kitagawa"], "parody": ["Sono Bisque Doll wa Koi o Suru"]},
        ),
        # Older posts separate with a hyphen.
        (
            "Momokun - Jane Doe (Zenless Zone Zero)",
            ["Jane Doe", "Momokun", "Zenless Zone Zero"],
            {"artist": ["Momokun"], "character": ["Jane Doe"], "parody": ["Zenless Zone Zero"]},
        ),
    ],
)
def test_classify_tags_places_cosplayer_character_and_series(nudecosplay, title, tags, expected):
    groups = nudecosplay._classify_tags(title, tags)
    assert {namespace: values for namespace, values in groups.items() if values} == expected


def test_classify_tags_rejects_a_qualified_tag_whose_series_contradicts_the_title(nudecosplay):
    groups = nudecosplay._classify_tags(
        "Umeko J – Jessie (Toy Story)", ["Jessie (Pokemon)", "Jessie (Toy Story)", "Umeko J"]
    )
    assert groups["character"] == ["Jessie (Toy Story)"]
    assert groups["general"] == ["Jessie (Pokemon)"]


def test_classify_tags_keeps_unconfirmed_tags_general_rather_than_guessing(nudecosplay):
    """Two leftovers could be character and series in either order."""
    groups = nudecosplay._classify_tags(
        "Cherry Neko 桜桃喵 – Rizu-kyun",
        ["Cherry Neko 桜桃喵", "Marin Kitagawa", "Sono Bisque Doll wa Koi\xa0o\xa0Suru"],
    )
    assert groups["artist"] == ["Cherry Neko 桜桃喵"]
    assert groups["character"] == groups["parody"] == []
    assert groups["general"] == ["Marin Kitagawa", "Sono Bisque Doll wa Koi\xa0o\xa0Suru"]


def test_classify_tags_lists_every_cosplayer_of_a_collab(nudecosplay):
    groups = nudecosplay._classify_tags(
        "Mikomin & Mikomi Hokina – Wednesday Addams & Mavis",
        ["Collab", "Hotel Transylvania", "Mavis", "Mikomi Hokina", "Mikomin", "The Addams Family", "Wednesday Addams"],
    )
    assert groups["artist"] == ["Mikomi Hokina", "Mikomin"]
    assert groups["character"] == ["Mavis", "Wednesday Addams"]
    assert groups["general"] == ["Collab", "Hotel Transylvania", "The Addams Family"]


def test_classify_tags_without_a_dash_in_the_title_has_no_artist(nudecosplay):
    groups = nudecosplay._classify_tags("Weekly Set", ["Weekly"])
    assert groups["artist"] == []
    assert groups["character"] == ["Weekly"]


# ── metadata ──


def test_metadata_uses_decoded_slug_as_gallery_id_and_unescaped_trimmed_title(nudecosplay):
    meta = nudecosplay._post_metadata(_POST)
    assert meta["gallery_id"] == _SLUG
    assert meta["id"] == 944160
    assert meta["title"] == "Walküre 絞肉姬 – Kal’tsit"
    assert meta["date"] == datetime(2026, 9, 21, 19, 40, 28)


def test_metadata_namespaces_tags_and_appends_site_categories_as_general(nudecosplay):
    meta = nudecosplay._post_metadata(_POST)
    assert meta["artist"] == "Walküre 絞肉姬"
    assert meta["tags"] == {
        "artist": ["Walküre 絞肉姬"],
        "character": ["Kal'tsit"],
        "parody": ["Arknights"],
        "general": ["Ero Cosplay", "Nude"],
    }


def test_metadata_without_embedded_terms_has_no_tags_and_empty_artist(nudecosplay):
    post = {key: value for key, value in _POST.items() if key != "_embedded"}
    meta = nudecosplay._post_metadata(post)
    assert meta["tags"] == {}
    assert meta["artist"] == ""


def test_metadata_fields_are_not_dropped_by_the_metadata_allowlist(nudecosplay):
    from plugins.builtin.gallery_dl.source import _METADATA_INCLUDE

    assert set(nudecosplay._post_metadata(_POST)) <= set(_METADATA_INCLUDE)


def test_extractor_metadata_raises_not_found_when_the_slug_is_not_a_post(nudecosplay):
    extractor = _extractor(nudecosplay, "https://nudecosplay.biz/about-us/")
    with pytest.raises(_NotFoundError):
        extractor.metadata("[]")


# ── images ──


def test_image_urls_keep_document_order_and_prefer_lazyload_data_src(nudecosplay):
    assert nudecosplay._image_urls(_POST["content"]["rendered"]) == [
        "https://nudecosplay.biz/wp-content/uploads/2026/09/Cover.jpg",
        "https://nudecosplay.biz/wp-content/uploads/2026/09/1.jpg?x=1&y=2",
        "https://nudecosplay.biz/wp-content/uploads/2026/09/2.webp",
    ]


def test_extractor_images_come_from_the_post_parsed_in_metadata(nudecosplay):
    extractor = _extractor(nudecosplay, "https://nudecosplay.biz/walkure-絞肉姬-kaltsit/")
    page = json.dumps([_POST])
    extractor.metadata(page)
    assert [url for url, _ in extractor.images(page)] == nudecosplay._image_urls(_POST["content"]["rendered"])


# ── Jyzrox wiring ──


def test_declared_site_registers_nudecosplay_as_a_gallery_site(nudecosplay_site):
    from plugins.builtin.gallery_dl._sites import _DEFAULT_CONFIG, get_site_by_domain, get_site_config

    cfg = get_site_config("nudecosplay")
    assert cfg is nudecosplay_site
    assert cfg is not _DEFAULT_CONFIG
    assert get_site_by_domain("nudecosplay.biz") is cfg
    assert cfg.category == "gallery"
    assert cfg.artist_fields == ("artist",)
    assert cfg.source_id_fields == ("gallery_id",)


def test_url_identity_is_the_decoded_slug_and_archive_entries_start_with_it(nudecosplay, monkeypatch):
    from plugins.builtin.gallery_dl import _identity

    url = "https://nudecosplay.biz/walkure-%E7%B5%9E%E8%82%89%E5%A7%AC-kaltsit/"
    extractor = _extractor(nudecosplay, url)
    monkeypatch.setattr(_identity, "_match_url", lambda url: ("nudecosplay", "gallery", extractor.groups))
    identity = _identity.resolve_url_identity(url)
    assert (identity.source, identity.source_id) == ("nudecosplay", f"gallery={_SLUG}")

    entry = nudecosplay.NudecosplayGalleryExtractor.archive_fmt.format(gallery_id=_SLUG, num=7)
    assert entry.startswith(f"{identity.source_id}_")


def test_sidecar_metadata_imports_title_namespaced_tags_date_and_cosplayer_as_artist(tmp_path, nudecosplay_site):
    from plugins.builtin.gallery_dl._metadata import parse_gallery_dl_import

    data = parse_gallery_dl_import(
        tmp_path,
        {
            "category": "nudecosplay",
            "subcategory": "gallery",
            "gallery_id": "plathong-cipher-honkai-star-rail",
            "id": 941722,
            "title": "Plathong – Cipher (Honkai: Star Rail)",
            "date": "2026-08-18 18:53:30",
            "tags": {"artist": ["Plathong"], "character": ["Cipher"], "parody": ["Honkai: Star Rail"]},
            "artist": "Plathong",
            "count": 7,
            "num": 1,
        },
    )
    assert data.title == "Plathong – Cipher (Honkai: Star Rail)"
    assert data.tags == ["artist:Plathong", "character:Cipher", "parody:Honkai: Star Rail"]
    assert data.artist_id == "nudecosplay:Plathong"
    assert data.posted_at == datetime(2026, 8, 18, 18, 53, 30, tzinfo=UTC)
