"""Sites declared by drop-in gallery-dl extractors (``JYZROX_SITE``).

A drop-in extractor outside GDL_SITES used to resolve to ``_DEFAULT_CONFIG``:
category "other", so ensure_gallery_from_identity() titled every gallery with
its identity string ("gallery=12345") and wrote no tags. Registering needed an
edit to ``_sites.py``, which lives in the image. These tests load extractor
files the way production does (``load_inprocess()``) and check every registry
consumer sees the declared site.
"""

import sys
import textwrap
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from plugins.builtin.gallery_dl import _extractors, _sites
from plugins.builtin.gallery_dl._identity import UrlIdentity
from tests.test_progressive_url_identity import _Harness

_EXTRACTOR_DIR = Path(__file__).resolve().parent.parent / "plugins" / "builtin" / "gallery_dl" / "extractors"


@pytest.fixture
def registry(monkeypatch):
    """Isolate the site registry: declarations made by one test never leak into another."""
    monkeypatch.setattr(_sites, "_BY_SOURCE", dict(_sites._BY_SOURCE))
    monkeypatch.setattr(_sites, "_BY_DOMAIN", dict(_sites._BY_DOMAIN))
    monkeypatch.setattr(_sites, "_EXTRA_SITES", [])
    monkeypatch.setattr(_sites, "_EXTRA_METADATA_FIELDS", [])
    return _sites


@pytest.fixture
def extractor_dir(tmp_path, monkeypatch, registry):
    """An empty extractor directory, loaded against a stub gallery-dl."""

    class _GalleryExtractor:
        def __init__(self, match, url=None):
            self.groups = match.groups()

    package = types.ModuleType("gallery_dl")
    extractor = types.ModuleType("gallery_dl.extractor")
    common = types.ModuleType("gallery_dl.extractor.common")
    common.GalleryExtractor = _GalleryExtractor
    # gallery_dl.extractor._get_classes, verbatim in spirit
    extractor.add_module = MagicMock(
        side_effect=lambda module: [
            cls
            for cls in module.__dict__.values()
            if hasattr(cls, "pattern") and getattr(cls, "__module__", None) == module.__name__
        ]
    )
    extractor.common = common
    package.extractor = extractor
    monkeypatch.setitem(sys.modules, "gallery_dl", package)
    monkeypatch.setitem(sys.modules, "gallery_dl.extractor", extractor)
    monkeypatch.setitem(sys.modules, "gallery_dl.extractor.common", common)

    monkeypatch.setattr(_extractors, "_BUNDLED_DIR", tmp_path)
    monkeypatch.setattr(_extractors, "_loaded", set())
    _extractors._module_names.cache_clear()
    yield tmp_path
    _extractors._module_names.cache_clear()
    for path in tmp_path.glob("*.py"):
        sys.modules.pop(path.stem, None)


def _write(directory: Path, name: str, site: str | None, category: str = "dropin") -> None:
    extractor = textwrap.dedent(
        f"""
        from gallery_dl.extractor.common import GalleryExtractor


        class DropinGalleryExtractor(GalleryExtractor):
            category = "{category}"
            pattern = r"(?:https?://)?(?:www\\.)?dropin\\.example/g/(\\d+)"
            example = "https://dropin.example/g/1"
        """
    )
    declaration = f"JYZROX_SITE = {site}\n" if site is not None else ""
    (directory / f"{name}.py").write_text(extractor + declaration)


_GALLERY_SITE = """{
    "domain": "www.Dropin.example",
    "name": "Drop-in",
    "category": "gallery",
    "has_tags": True,
    "title_fields": ["name", "title"],
    "artist_fields": ["studio.name"],
    "metadata_include": ["studio"],
    "retries": 7,
}"""


# ── registration reaches every registry consumer ──


def test_declared_site_is_seen_by_every_site_lookup(extractor_dir, registry):
    _write(extractor_dir, "dropin_gallery", _GALLERY_SITE)
    assert _extractors.load_inprocess() == ["dropin_gallery"]

    cfg = registry.get_site_config("dropin")
    assert cfg is not registry._DEFAULT_CONFIG
    assert (cfg.source_id, cfg.domain, cfg.name, cfg.category) == ("dropin", "dropin.example", "Drop-in", "gallery")
    assert cfg.title_fields == ("name", "title")
    assert registry.get_site_by_domain("dropin.example") is cfg
    assert cfg in registry.all_sites()
    assert registry.gdl_extractor_name("dropin") == "dropin"

    from core.site_config import SiteConfigService
    from plugins.builtin.gallery_dl.source import GalleryDlPlugin, _metadata_include

    assert SiteConfigService()._merge("dropin", None).retries == 7
    # Fields the declaration reads must survive the metadata postprocessor.
    assert {"name", "studio"} <= set(_metadata_include())

    from plugins.registry import PluginRegistry

    plugins = PluginRegistry()
    plugins.register(GalleryDlPlugin())
    info = plugins.detect_source_info("https://www.dropin.example/g/12345")
    assert (info.source_id, info.category, info.has_tags) == ("dropin", "gallery", True)
    assert plugins.detect_source("https://dropin.example/g/12345") == "dropin"


async def test_declared_site_is_listed_for_site_config(extractor_dir, registry):
    from unittest.mock import AsyncMock, patch

    _write(extractor_dir, "dropin_gallery", _GALLERY_SITE)
    _extractors.load_inprocess()

    session = AsyncMock()
    session.execute.return_value = MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))))
    factory = MagicMock()
    factory.return_value.__aenter__.return_value = session
    from core.site_config import SiteConfigService

    with patch("core.site_config.AsyncSessionLocal", factory):
        params = await SiteConfigService().get_all_download_params()
    assert params["dropin"].retries == 7


async def test_dropin_gallery_site_gets_its_title_and_tags_from_metadata(extractor_dir):
    """Regression: an unregistered gallery site was titled "gallery=12345" with no tags."""
    _write(extractor_dir, "dropin_gallery", _GALLERY_SITE)
    _extractors.load_inprocess()

    harness = _Harness()
    await harness.run(
        harness.make("https://dropin.example/g/12345"),
        UrlIdentity("dropin", "gallery=12345", False, "dropin"),
        {"category": "dropin", "gallery_id": 12345, "name": "A Real Title", "tags": ["model:someone"]},
    )

    params, _ = harness.last()
    assert (params["source"], params["source_id"]) == ("dropin", "gallery=12345")
    assert params["title"] == "A Real Title"
    assert params["tags_array"] == ["model:someone"]
    assert harness.tag_calls == [(42, ["model:someone"])]


async def test_undeclared_dropin_site_still_falls_back_to_the_identity_title(extractor_dir):
    _write(extractor_dir, "dropin_gallery", None)
    _extractors.load_inprocess()

    harness = _Harness()
    await harness.run(
        harness.make("https://dropin.example/g/12345"),
        UrlIdentity("dropin", "gallery=12345", False, "dropin"),
        {"category": "dropin", "gallery_id": 12345, "title": "A Real Title", "tags": ["model:someone"]},
    )

    params, _ = harness.last()
    assert params["title"] == "gallery=12345"
    assert not params["tags_array"]


def test_list_declares_one_site_per_category(extractor_dir, registry):
    (extractor_dir / "two_sites.py").write_text(
        textwrap.dedent(
            """
            JYZROX_SITE = [
                {"source_id": "alpha", "domain": "alpha.example", "name": "Alpha", "category": "art"},
                {"source_id": "beta", "domain": "beta.example", "name": "Beta", "category": "gallery"},
            ]

            class AlphaExtractor:
                category = "alpha"
                pattern = "alpha"

            class BetaExtractor:
                category = "beta"
                pattern = "beta"
            """
        )
    )
    _extractors.load_inprocess()

    assert registry.get_site_config("alpha").domain == "alpha.example"
    assert registry.get_site_config("beta").category == "gallery"


# ── static entries win; bad declarations never block the extractor ──


def test_declaration_cannot_redefine_a_built_in_source(extractor_dir, registry):
    static = registry.get_site_config("pixiv")
    _write(extractor_dir, "fake_pixiv", '{"domain": "pixiv.example", "name": "Fake", "category": "art"}', "pixiv")

    assert _extractors.load_inprocess() == ["fake_pixiv"]
    assert registry.get_site_config("pixiv") is static
    assert registry.get_site_by_domain("pixiv.example") is registry._DEFAULT_CONFIG


def test_declaration_cannot_take_over_a_built_in_domain(extractor_dir, registry):
    static = registry.get_site_by_domain("nhentai.net")
    _write(extractor_dir, "hijack", '{"domain": "nhentai.net", "name": "Hijack", "category": "gallery"}')

    _extractors.load_inprocess()
    assert registry.get_site_by_domain("nhentai.net") is static
    assert registry.get_site_config("dropin") is registry._DEFAULT_CONFIG


@pytest.mark.parametrize(
    ("site", "reason"),
    [
        ('{"domain": "dropin.example", "name": "D", "category": "gallery", "colour": "red"}', "unsupported keys"),
        ('{"domain": "dropin.example", "name": "D"}', "missing required keys"),
        ('{"domain": "dropin.example", "name": "D", "category": "videos"}', "category must be one of"),
        ('{"domain": "dropin.example", "name": "D", "category": "gallery", "has_tags": "yes"}', "has_tags"),
        ('{"domain": "dropin.example", "name": "D", "category": "gallery", "image_order": "random"}', "image_order"),
        ('{"domain": "https://dropin.example/", "name": "D", "category": "gallery"}', "bare host name"),
        ('{"domain": "d.example", "name": "D", "category": "gallery", "source_id": "other"}', "not an extractor"),
        ('{"domain": "d.example", "name": "D", "category": "gallery", "extractor": "x"}', "unsupported keys"),
        (
            '{"domain": "d.example", "name": "D", "category": "gallery", "metadata_include": ["a b"]}',
            "invalid metadata",
        ),
        ('"dropin.example"', "must be a dict"),
    ],
)
def test_invalid_declaration_is_ignored_but_the_extractor_still_loads(extractor_dir, registry, caplog, site, reason):
    _write(extractor_dir, "dropin_gallery", site)

    assert _extractors.load_inprocess() == ["dropin_gallery"]
    assert registry.get_site_config("dropin") is registry._DEFAULT_CONFIG
    assert registry.all_sites() == registry.GDL_SITES
    assert reason in caplog.text


# ── bundled extractors ──


def test_every_bundled_extractor_registers_its_site_through_jyzrox_site(extractor_dir, registry):
    """Bundled extractors need no GDL_SITES entry, init.sql table or migration."""
    for path in _EXTRACTOR_DIR.glob("*.py"):
        (extractor_dir / path.name).write_text(path.read_text(encoding="utf-8"))
    assert {s.source_id for s in registry.GDL_SITES}.isdisjoint(
        {p.stem.split("_")[0] for p in _EXTRACTOR_DIR.glob("*.py")}
    )

    loaded = _extractors.load_inprocess()
    assert "xiuren7_gallery" in loaded

    cfg = registry.get_site_config("xiuren7")
    assert cfg is not registry._DEFAULT_CONFIG
    assert registry.get_site_by_domain("xiuren7.com") is cfg
    # Title and tags are read from metadata only for gallery/manga sites.
    assert (cfg.name, cfg.category, cfg.has_tags) == ("XiuRen7", "gallery", True)
    assert cfg.source_id_fields == ("gallery_id",)
    assert cfg.artist_fields == ("artist",)
    assert registry.gdl_extractor_name("xiuren7") == "xiuren7"
