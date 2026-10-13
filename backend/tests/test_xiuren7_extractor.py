"""Tests for the bundled xiuren7 gallery-dl extractor and its Jyzrox wiring."""

import importlib.util
import re
import sys
import types
from datetime import UTC, datetime
from pathlib import Path

import pytest

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_EXTRACTOR_DIR = _BACKEND_DIR / "plugins" / "builtin" / "gallery_dl" / "extractors"
_INIT_SQL = (_BACKEND_DIR.parent / "db" / "init.sql").read_text(encoding="utf-8")
_MIGRATION = _BACKEND_DIR / "migrations" / "versions" / "0031_xiuren7_archive_table.py"

_CATEGORY_RE = re.compile(r'^\s+category = "(\w+)"', re.MULTILINE)

_POST = {
    "id": 463684,
    "date_gmt": "2026-03-19T02:39:43",
    "title": {"rendered": " [Studio] 2026.02.02 No.1 Model &#8211; Set "},
    "content": {
        "rendered": (
            '<p><img alt="1" decoding="async" src="https://img.example/a/1.jpg"  /><br />\n'
            '<img alt="2" src="https://img.example/thumb.svg" data-src="//img.example/a/2.jpg?x=1&amp;y=2" />\n'
            '<img alt="no source" />\n'
            '<IMG SRC="https://img.example/a/3.webp"></p>'
        )
    },
    "_embedded": {
        "wp:term": [
            [{"taxonomy": "category", "name": "Studio"}],
            [{"taxonomy": "post_tag", "name": "Model &amp; Co"}],
        ]
    },
}


@pytest.fixture
def xiuren7(monkeypatch):
    """Import the extractor module against a stub of the gallery-dl base class."""

    class _GalleryExtractor:
        def __init__(self, match, url=None):
            self.groups = match.groups()
            self.page_url = url

    package = types.ModuleType("gallery_dl")
    extractor = types.ModuleType("gallery_dl.extractor")
    common = types.ModuleType("gallery_dl.extractor.common")
    common.GalleryExtractor = _GalleryExtractor
    package.extractor = extractor
    extractor.common = common
    monkeypatch.setitem(sys.modules, "gallery_dl", package)
    monkeypatch.setitem(sys.modules, "gallery_dl.extractor", extractor)
    monkeypatch.setitem(sys.modules, "gallery_dl.extractor.common", common)

    spec = importlib.util.spec_from_file_location("xiuren7_gallery_under_test", _EXTRACTOR_DIR / "xiuren7_gallery.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _archive_tables() -> dict[str, str]:
    return {
        name: body
        for name, body in re.findall(r"CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\);", _INIT_SQL, re.DOTALL)
        if re.search(r"^\s*entry\s+TEXT PRIMARY KEY", body, re.MULTILINE)
    }


def _columns(body: str) -> list[str]:
    return [" ".join(line.split()).rstrip(",") for line in body.strip().splitlines() if line.strip()]


def _bundled_categories() -> list[str]:
    return sorted(
        {c for path in _EXTRACTOR_DIR.glob("*.py") for c in _CATEGORY_RE.findall(path.read_text(encoding="utf-8"))}
    )


# ── URL matching ──


@pytest.mark.parametrize(
    "url",
    [
        "http://www.xiuren7.com/463684.html",
        "https://www.xiuren7.com/463684.html",
        "http://xiuren7.com/463684.html",
        "www.xiuren7.com/463684.html",
    ],
)
def test_pattern_matches_post_url_with_any_scheme_or_www(xiuren7, url):
    match = re.match(xiuren7.Xiuren7GalleryExtractor.pattern, url)
    assert match is not None
    assert match.group(1) == "463684"


@pytest.mark.parametrize(
    "url",
    [
        "http://www.xiuren7.com/xiuren",
        "http://www.xiuren7.com/tag/somebody",
        "http://www.xiuren7.com/vip",
        "http://www.notxiuren7.com.example/463684.html",
    ],
)
def test_pattern_rejects_listing_pages_and_other_hosts(xiuren7, url):
    assert re.match(xiuren7.Xiuren7GalleryExtractor.pattern, url) is None


def test_extractor_requests_rest_api_over_plain_http_not_the_html_page(xiuren7):
    cls = xiuren7.Xiuren7GalleryExtractor
    extractor = cls(re.match(cls.pattern, "https://xiuren7.com/463684.html"))
    assert extractor.page_url == "http://www.xiuren7.com/wp-json/wp/v2/posts/463684?_embed=wp:term"


# ── metadata ──


def test_metadata_uses_numeric_post_id_and_unescaped_trimmed_title(xiuren7):
    meta = xiuren7._post_metadata(_POST)
    assert meta["gallery_id"] == 463684
    assert meta["title"] == "[Studio] 2026.02.02 No.1 Model – Set"
    assert meta["date"] == datetime(2026, 3, 19, 2, 39, 43)


def test_metadata_takes_tags_from_post_tag_terms_only_and_first_as_artist(xiuren7):
    meta = xiuren7._post_metadata(_POST)
    assert meta["tags"] == ["Model & Co"]
    assert meta["artist"] == "Model & Co"


def test_metadata_without_embedded_terms_has_no_tags_and_empty_artist(xiuren7):
    post = {key: value for key, value in _POST.items() if key != "_embedded"}
    meta = xiuren7._post_metadata(post)
    assert meta["tags"] == []
    assert meta["artist"] == ""


def test_metadata_fields_are_not_dropped_by_the_metadata_allowlist(xiuren7):
    from plugins.builtin.gallery_dl.source import _METADATA_INCLUDE

    assert set(xiuren7._post_metadata(_POST)) <= set(_METADATA_INCLUDE)


# ── images ──


def test_image_urls_keep_document_order_and_prefer_lazyload_data_src(xiuren7):
    assert xiuren7._image_urls(_POST["content"]["rendered"]) == [
        "https://img.example/a/1.jpg",
        "http://img.example/a/2.jpg?x=1&y=2",
        "https://img.example/a/3.webp",
    ]


def test_image_urls_empty_for_content_without_images(xiuren7):
    assert xiuren7._image_urls("<p>video only</p>") == []


def test_extractor_images_come_from_the_json_parsed_in_metadata(xiuren7):
    import json

    cls = xiuren7.Xiuren7GalleryExtractor
    extractor = cls(re.match(cls.pattern, "http://www.xiuren7.com/463684.html"))
    page = json.dumps(_POST)
    assert extractor.metadata(page)["gallery_id"] == 463684
    assert extractor.images(page) == [
        ("https://img.example/a/1.jpg", None),
        ("http://img.example/a/2.jpg?x=1&y=2", None),
        ("https://img.example/a/3.webp", None),
    ]


# ── Jyzrox wiring ──


def test_site_is_registered_so_archive_linking_does_not_fall_back_to_gallery_dl_table():
    from plugins.builtin.gallery_dl._sites import _DEFAULT_CONFIG, get_site_by_domain, get_site_config

    cfg = get_site_config("xiuren7")
    assert cfg is not _DEFAULT_CONFIG
    assert cfg.source_id == "xiuren7"
    assert get_site_by_domain("xiuren7.com") is cfg
    # Title and tags are read from metadata only for gallery/manga sites.
    assert cfg.category == "gallery"
    assert cfg.source_id_fields == ("gallery_id",)
    assert cfg.artist_fields == ("artist",)


def test_archive_entries_start_with_the_url_identity_so_they_link_by_prefix(xiuren7, monkeypatch):
    """Archive linking matches ``entry LIKE '<source_id>%'`` first.

    An entry that does not start with the gallery's source_id falls back to
    linking every unlinked entry written while the job ran, which attaches
    entries to the wrong gallery when two downloads of this site overlap.
    """
    from plugins.builtin.gallery_dl import _identity

    monkeypatch.setattr(_identity, "_match_url", lambda url: ("xiuren7", "gallery", ("463684",)))
    identity = _identity.resolve_url_identity("http://www.xiuren7.com/463684.html")
    assert (identity.source, identity.source_id) == ("xiuren7", "gallery=463684")

    entry = xiuren7.Xiuren7GalleryExtractor.archive_fmt.format(gallery_id=463684, num=7)
    assert entry.startswith(f"{identity.source_id}_")


def test_sidecar_metadata_imports_title_tags_date_and_model_as_artist(tmp_path):
    from plugins.builtin.gallery_dl._metadata import parse_gallery_dl_import

    data = parse_gallery_dl_import(
        tmp_path,
        {
            "category": "xiuren7",
            "subcategory": "gallery",
            "gallery_id": 463684,
            "title": "[Studio] 2026.02.02 No.1 Model",
            "date": "2026-03-19 02:39:43",
            "tags": ["Model"],
            "artist": "Model",
            "count": 2,
            "num": 1,
        },
    )
    assert (data.source, data.source_id) == ("xiuren7", "463684")
    assert data.title == "[Studio] 2026.02.02 No.1 Model"
    assert data.tags == ["Model"]
    assert data.artist_id == "xiuren7:Model"
    assert data.posted_at == datetime(2026, 3, 19, 2, 39, 43, tzinfo=UTC)


def test_bundled_extractor_category_without_registered_archive_table_is_rejected():
    """Every bundled extractor needs a pre-created archive table Jyzrox can link.

    gallery-dl creates a missing table as ``(entry TEXT PRIMARY KEY)``, and an
    unregistered category resolves to a table named ``gallery_dl``; either way
    entries never link to a gallery and a re-download finishes with 0 images.
    """
    from plugins.builtin.gallery_dl._sites import get_site_config

    categories = _bundled_categories()
    assert "xiuren7" in categories
    tables = _archive_tables()
    for category in categories:
        cfg = get_site_config(category)
        assert (cfg.extractor or cfg.source_id) == category
        assert category in tables
        assert re.search(
            r"^\s*gallery_id\s+BIGINT REFERENCES galleries\(id\) ON DELETE CASCADE", tables[category], re.M
        )
        assert re.search(r"^\s*job_id\s+UUID", tables[category], re.M)
        assert f"idx_{category}_unlinked ON {category} (job_id) WHERE gallery_id IS NULL" in _INIT_SQL


def test_migration_0031_creates_the_same_archive_table_as_init_sql_idempotently():
    spec = importlib.util.spec_from_file_location("migration_0031", _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0031"
    assert module.down_revision == "0030"

    executed: list[str] = []
    module.op = type("Op", (), {"execute": staticmethod(executed.append)})
    module.upgrade()

    create = next(sql for sql in executed if "CREATE TABLE" in sql)
    name, body = re.fullmatch(r"CREATE TABLE IF NOT EXISTS (\w+) \((.*)\)", create.strip(), re.DOTALL).groups()
    assert name == "xiuren7"
    # init.sql is HEAD: migration 0032 later gave job_id its default.
    from plugins.builtin.gallery_dl._archive import ARCHIVE_JOB_ID_DEFAULT

    head_columns = [
        column.removesuffix(f" DEFAULT {ARCHIVE_JOB_ID_DEFAULT}") for column in _columns(_archive_tables()["xiuren7"])
    ]
    assert _columns(body) == head_columns
    index = next(sql for sql in executed if "CREATE INDEX" in sql)
    assert "CREATE INDEX IF NOT EXISTS idx_xiuren7_unlinked ON xiuren7 (job_id) WHERE gallery_id IS NULL" in index

    executed.clear()
    module.downgrade()
    assert executed == ["DROP TABLE IF EXISTS xiuren7"]
