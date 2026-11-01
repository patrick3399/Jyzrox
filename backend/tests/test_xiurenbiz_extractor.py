"""Tests for the bundled xiuren.biz gallery-dl extractor and its Jyzrox wiring."""

import importlib.util
import json
import re
import sys
import types
from datetime import UTC, datetime
from pathlib import Path

import pytest

_EXTRACTOR_DIR = Path(__file__).resolve().parent.parent / "plugins" / "builtin" / "gallery_dl" / "extractors"

_SLUG = "xiuren-extra-fw0087-利世"

_POST = {
    "id": 1349336,
    "slug": "xiuren-extra-fw0087-%e5%88%a9%e4%b8%96",
    "date_gmt": "2026-05-11T18:37:43",
    "title": {"rendered": " XiuRen Extra FW0087 &#8211; 利世 "},
    "content": {
        "rendered": (
            '<p><a href="https://xiuren.biz/wp-content/uploads/2026/05/a.jpg">'
            '<img decoding="async" src="https://xiuren.biz/wp-content/uploads/2026/05/a.jpg" /></a><br />\n'
            '<img src="https://xiuren.biz/lazy.svg" data-src="//xiuren.biz/wp-content/uploads/2026/05/b.jpg?x=1&amp;y=2" />\n'
            '<img alt="no source" />\n'
            '<IMG SRC="https://xiuren.biz/wp-content/uploads/2026/05/c.webp"></p>'
        )
    },
    "_embedded": {
        "wp:term": [
            [{"taxonomy": "category", "name": "XiuRen Extra", "slug": "xiuren-extra"}],
            [
                {"taxonomy": "post_tag", "name": "Xiuren", "slug": "xiuren"},
                {"taxonomy": "post_tag", "name": "XiuRen Extra", "slug": "xiuren-extra"},
                {"taxonomy": "post_tag", "name": "利世", "slug": "%e5%88%a9%e4%b8%96"},
            ],
        ]
    },
}

# Site-wide categories: studio labels such as "XiuRen" double as post tags.
_CATEGORIES = [
    {"name": "XiuRen", "slug": "xiuren"},
    {"name": "XiuRen Extra", "slug": "xiuren-extra"},
    {"name": "Cosplay", "slug": "cosplay"},
    {"name": "Hot Girl", "slug": "hot-girl"},
]


class _NotFoundError(Exception):
    pass


@pytest.fixture
def xiurenbiz(monkeypatch):
    """Import the extractor module against a stub of the gallery-dl surface it uses."""

    class _Response:
        def __init__(self, data):
            self._data = data

        def json(self):
            return self._data

    class _GalleryExtractor:
        def __init__(self, match, url=None):
            self.groups = match.groups()
            self.page_url = url
            self.requested: list[str] = []

        def request(self, url, **kwargs):
            self.requested.append(url)
            return _Response(_CATEGORIES)

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
        "xiurenbiz_gallery_under_test", _EXTRACTOR_DIR / "xiurenbiz_gallery.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def xiurenbiz_site(xiurenbiz, monkeypatch):
    """Register the module's JYZROX_SITE the way load_inprocess() does, in an isolated registry."""
    from plugins.builtin.gallery_dl import _sites

    monkeypatch.setattr(_sites, "_BY_SOURCE", dict(_sites._BY_SOURCE))
    monkeypatch.setattr(_sites, "_BY_DOMAIN", dict(_sites._BY_DOMAIN))
    monkeypatch.setattr(_sites, "_EXTRA_SITES", [])
    monkeypatch.setattr(_sites, "_EXTRA_METADATA_FIELDS", [])
    config, fields = _sites.site_config_from_declaration(
        xiurenbiz.JYZROX_SITE, {xiurenbiz.XiurenbizGalleryExtractor.category}
    )
    assert _sites.register_site(config, fields) is None
    return config


def _extractor(module, url):
    cls = module.XiurenbizGalleryExtractor
    return cls(re.match(cls.pattern, url))


# ── URL matching ──


@pytest.mark.parametrize(
    "url",
    [
        "https://xiuren.biz/xiuren-extra-fw0087-%E5%88%A9%E4%B8%96/",
        "https://xiuren.biz/xiuren-extra-fw0087-%e5%88%a9%e4%b8%96/",
        "https://xiuren.biz/xiuren-extra-fw0087-利世/",
        "http://www.xiuren.biz/xiuren-extra-fw0087-%E5%88%A9%E4%B8%96",
        "xiuren.biz/xiuren-extra-fw0087-%E5%88%A9%E4%B8%96/?utm_source=x",
        "https://xiuren.biz/xiuren-extra-fw0087-%E5%88%A9%E4%B8%96/#comments",
    ],
)
def test_pattern_matches_post_url_in_any_encoding_scheme_or_suffix(xiurenbiz, url):
    assert re.match(xiurenbiz.XiurenbizGalleryExtractor.pattern, url) is not None


@pytest.mark.parametrize(
    "url",
    [
        "https://xiuren.biz/",
        "https://xiuren.biz/category/xiuren-extra/",
        "https://xiuren.biz/tag/%e5%88%a9%e4%b8%96/",
        "https://xiuren.biz/page/2/",
        "https://xiuren.biz/category/",
        "https://xiuren.biz/popular-this-month/",
        "https://xiuren.biz/most_popular/",
        "https://xiuren.biz/latest-post/",
        "https://xiuren.biz/xmlrpc.php",
        "https://xiuren.biz/wp-json/",
        "https://xiuren.biz/xiuren-vol-9920/2/",
        "https://xiuren.biz/wp-content/uploads/2026/05/a.jpg",
        "https://notxiuren.biz.example/xiuren-vol-9920/",
    ],
)
def test_pattern_rejects_listing_pages_files_and_other_hosts(xiurenbiz, url):
    assert re.match(xiurenbiz.XiurenbizGalleryExtractor.pattern, url) is None


@pytest.mark.parametrize(
    "url",
    [
        "https://xiuren.biz/xiuren-extra-fw0087-%E5%88%A9%E4%B8%96/",
        "https://xiuren.biz/xiuren-extra-fw0087-%e5%88%a9%e4%b8%96/",
        "https://xiuren.biz/xiuren-extra-fw0087-利世/",
        "https://xiuren.biz/XiuRen-Extra-FW0087-%E5%88%A9%E4%B8%96",
    ],
)
def test_identity_groups_are_the_decoded_lowercase_slug_whatever_the_url_encoding(xiurenbiz, url):
    """Jyzrox keys the gallery by the match groups (ADR 0016).

    Browsers copy the slug with uppercase percent-escapes while the site links
    to itself in lowercase; raw groups would make those two galleries.
    """
    assert _extractor(xiurenbiz, url).groups == (_SLUG,)


def test_extractor_requests_rest_api_by_slug_not_the_html_page(xiurenbiz):
    extractor = _extractor(xiurenbiz, "https://xiuren.biz/xiuren-extra-fw0087-利世/")
    assert extractor.page_url == (
        "https://xiuren.biz/wp-json/wp/v2/posts?slug=xiuren-extra-fw0087-%E5%88%A9%E4%B8%96&_embed=wp:term"
    )


# ── metadata ──


def test_metadata_uses_decoded_slug_as_gallery_id_and_unescaped_trimmed_title(xiurenbiz):
    meta = xiurenbiz._post_metadata(_POST, set())
    assert meta["gallery_id"] == _SLUG
    assert meta["id"] == 1349336
    assert meta["title"] == "XiuRen Extra FW0087 – 利世"
    assert meta["date"] == datetime(2026, 5, 11, 18, 37, 43)


def test_metadata_model_is_the_tag_that_is_not_a_category_name_case_insensitively(xiurenbiz):
    meta = xiurenbiz._post_metadata(_POST, xiurenbiz._category_keys(_CATEGORIES))
    assert meta["artist"] == "利世"
    assert meta["tags"] == {"artist": ["利世"], "general": ["Xiuren", "XiuRen Extra"]}


def test_metadata_keeps_every_model_when_a_post_has_several(xiurenbiz):
    post = {
        **_POST,
        "_embedded": {
            "wp:term": [
                [{"taxonomy": "category", "name": "Cosplay"}, {"taxonomy": "category", "name": "Hot Girl"}],
                [{"taxonomy": "post_tag", "name": "Kokuhui"}, {"taxonomy": "post_tag", "name": "Yuuhui玉汇"}],
            ]
        },
    }
    meta = xiurenbiz._post_metadata(post, xiurenbiz._category_keys(_CATEGORIES))
    assert meta["artist"] == "Kokuhui"
    assert meta["tags"] == {"artist": ["Kokuhui", "Yuuhui玉汇"], "general": ["Cosplay", "Hot Girl"]}


def test_metadata_with_only_studio_tags_has_no_artist(xiurenbiz):
    post = {
        **_POST,
        "_embedded": {"wp:term": [[{"taxonomy": "post_tag", "name": "Xiuren", "slug": "xiuren"}]]},
    }
    meta = xiurenbiz._post_metadata(post, xiurenbiz._category_keys(_CATEGORIES))
    assert meta["artist"] == ""
    assert meta["tags"] == {"general": ["Xiuren"]}


def test_metadata_without_embedded_terms_has_no_tags_and_empty_artist(xiurenbiz):
    post = {key: value for key, value in _POST.items() if key != "_embedded"}
    meta = xiurenbiz._post_metadata(post, set())
    assert meta["tags"] == {}
    assert meta["artist"] == ""


def test_metadata_fields_are_not_dropped_by_the_metadata_allowlist(xiurenbiz):
    from plugins.builtin.gallery_dl.source import _METADATA_INCLUDE

    assert set(xiurenbiz._post_metadata(_POST, set())) <= set(_METADATA_INCLUDE)


def test_extractor_metadata_excludes_site_category_names_fetched_from_rest(xiurenbiz):
    extractor = _extractor(xiurenbiz, "https://xiuren.biz/xiuren-extra-fw0087-利世/")
    meta = extractor.metadata(json.dumps([_POST]))
    assert meta["artist"] == "利世"
    assert extractor.requested == ["https://xiuren.biz/wp-json/wp/v2/categories?per_page=100&_fields=name,slug"]


def test_extractor_metadata_raises_not_found_when_the_slug_is_not_a_post(xiurenbiz):
    extractor = _extractor(xiurenbiz, "https://xiuren.biz/about-us/")
    with pytest.raises(_NotFoundError):
        extractor.metadata("[]")


# ── images ──


def test_image_urls_keep_document_order_and_prefer_lazyload_data_src(xiurenbiz):
    assert xiurenbiz._image_urls(_POST["content"]["rendered"]) == [
        "https://xiuren.biz/wp-content/uploads/2026/05/a.jpg",
        "https://xiuren.biz/wp-content/uploads/2026/05/b.jpg?x=1&y=2",
        "https://xiuren.biz/wp-content/uploads/2026/05/c.webp",
    ]


def test_extractor_images_come_from_the_post_parsed_in_metadata(xiurenbiz):
    extractor = _extractor(xiurenbiz, "https://xiuren.biz/xiuren-extra-fw0087-利世/")
    page = json.dumps([_POST])
    extractor.metadata(page)
    assert [url for url, _ in extractor.images(page)] == [
        "https://xiuren.biz/wp-content/uploads/2026/05/a.jpg",
        "https://xiuren.biz/wp-content/uploads/2026/05/b.jpg?x=1&y=2",
        "https://xiuren.biz/wp-content/uploads/2026/05/c.webp",
    ]


# ── Jyzrox wiring ──


def test_declared_site_registers_xiurenbiz_as_a_gallery_site(xiurenbiz_site):
    from plugins.builtin.gallery_dl._sites import _DEFAULT_CONFIG, get_site_by_domain, get_site_config

    cfg = get_site_config("xiurenbiz")
    assert cfg is xiurenbiz_site
    assert cfg is not _DEFAULT_CONFIG
    assert get_site_by_domain("xiuren.biz") is cfg
    # Title and tags are read from metadata only for gallery/manga sites.
    assert cfg.category == "gallery"
    assert cfg.artist_fields == ("artist",)
    assert cfg.source_id_fields == ("gallery_id",)


def test_url_identity_is_the_decoded_slug_and_archive_entries_start_with_it(xiurenbiz, monkeypatch):
    from plugins.builtin.gallery_dl import _identity

    extractor = _extractor(xiurenbiz, "https://xiuren.biz/xiuren-extra-fw0087-%E5%88%A9%E4%B8%96/")
    monkeypatch.setattr(_identity, "_match_url", lambda url: ("xiurenbiz", "gallery", extractor.groups))
    identity = _identity.resolve_url_identity("https://xiuren.biz/xiuren-extra-fw0087-%E5%88%A9%E4%B8%96/")
    assert (identity.source, identity.source_id) == ("xiurenbiz", f"gallery={_SLUG}")

    entry = xiurenbiz.XiurenbizGalleryExtractor.archive_fmt.format(gallery_id=_SLUG, num=7)
    assert entry.startswith(f"{identity.source_id}_")


def test_sidecar_metadata_imports_title_namespaced_tags_date_and_model_as_artist(tmp_path, xiurenbiz_site):
    from plugins.builtin.gallery_dl._metadata import parse_gallery_dl_import

    data = parse_gallery_dl_import(
        tmp_path,
        {
            "category": "xiurenbiz",
            "subcategory": "gallery",
            "gallery_id": _SLUG,
            "id": 1349336,
            "title": "XiuRen Extra FW0087 利世",
            "date": "2026-05-11 18:37:43",
            "tags": {"artist": ["利世"], "general": ["Xiuren"]},
            "artist": "利世",
            "count": 75,
            "num": 1,
        },
    )
    assert data.title == "XiuRen Extra FW0087 利世"
    assert data.tags == ["artist:利世", "general:Xiuren"]
    assert data.artist_id == "xiurenbiz:利世"
    assert data.posted_at == datetime(2026, 5, 11, 18, 37, 43, tzinfo=UTC)
