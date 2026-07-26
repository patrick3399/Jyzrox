"""Tests for bundled custom gallery-dl extractor discovery and loading."""

import json
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from plugins.builtin.gallery_dl import _extractors


@pytest.fixture
def bundled_dir(tmp_path, monkeypatch):
    """Point the bundled-extractor directory at an empty temp dir."""
    monkeypatch.setattr(_extractors, "_BUNDLED_DIR", tmp_path)
    monkeypatch.setattr(_extractors, "_loaded", set())
    _extractors._module_names.cache_clear()
    yield tmp_path
    _extractors._module_names.cache_clear()


class _FakeGalleryDl(types.ModuleType):
    """Stand-in for the ``gallery_dl`` package with only the attribute we touch."""

    extractor: types.SimpleNamespace


@pytest.fixture
def fake_gallery_dl(monkeypatch):
    """Install a stub ``gallery_dl`` exposing a recording ``extractor.add_module``."""
    package = _FakeGalleryDl("gallery_dl")
    package.extractor = types.SimpleNamespace(add_module=MagicMock())
    monkeypatch.setitem(sys.modules, "gallery_dl", package)
    return package.extractor


@pytest.fixture
def mock_config_path(tmp_path):
    """Mock settings.gallery_dl_config to a temp file."""
    config_file = tmp_path / "gallery-dl.json"
    with patch("plugins.builtin.gallery_dl.source.settings") as mock_settings:
        mock_settings.data_gallery_path = "/data/gallery"
        mock_settings.gallery_dl_config = str(config_file)
        mock_settings.gdl_archive_dsn = "postgresql://test:test@localhost:5432/test"
        yield config_file


@pytest.fixture(autouse=True)
def mock_site_config_service():
    """Prevent _build_gallery_dl_config from querying the real DB or Redis."""
    from tests.helpers import make_mock_site_config_svc

    svc = make_mock_site_config_svc()
    mock_pipeline = MagicMock()
    mock_pipeline.get = MagicMock()
    mock_pipeline.execute = AsyncMock(return_value=[])
    mock_redis = MagicMock()
    mock_redis.pipeline = MagicMock(return_value=mock_pipeline)
    mock_redis.get = AsyncMock(return_value=None)
    with (
        patch("core.site_config.site_config_service", svc),
        patch("core.redis_client.get_redis", return_value=mock_redis),
    ):
        yield svc


def _write_extractor(directory, name: str, body: str = "pattern = 'x'\n") -> None:
    (directory / f"{name}.py").write_text(body)


# ── extractor_source_dirs ──


def test_extractor_source_dirs_empty_when_nothing_bundled(bundled_dir):
    assert _extractors.extractor_source_dirs() == []


def test_extractor_source_dirs_ignores_non_python_files(bundled_dir):
    """A directory holding only the README must not count as a source dir."""
    (bundled_dir / "README.md").write_text("docs")
    assert _extractors.extractor_source_dirs() == []


def test_extractor_source_dirs_returns_dir_once_an_extractor_exists(bundled_dir):
    _write_extractor(bundled_dir, "example_site")
    assert _extractors.extractor_source_dirs() == [str(bundled_dir)]


def test_extractor_source_dirs_empty_when_directory_missing(tmp_path, monkeypatch):
    """A checkout without the extractors dir must not raise."""
    monkeypatch.setattr(_extractors, "_BUNDLED_DIR", tmp_path / "does-not-exist")
    _extractors._module_names.cache_clear()
    try:
        assert _extractors.extractor_source_dirs() == []
    finally:
        _extractors._module_names.cache_clear()


# ── config generation ──


@pytest.mark.asyncio
async def test_config_omits_module_sources_when_nothing_bundled(bundled_dir, mock_config_path):
    """Default install: emitted config must be identical to the pre-feature output."""
    from plugins.builtin.gallery_dl.source import _build_gallery_dl_config

    await _build_gallery_dl_config({})
    config = json.loads(mock_config_path.read_text())
    assert "module-sources" not in config["extractor"]


@pytest.mark.asyncio
async def test_config_module_sources_keeps_builtin_extractors(bundled_dir, mock_config_path):
    """A bare [dir] would disable every built-in extractor — the null entry restores them."""
    _write_extractor(bundled_dir, "example_site")
    from plugins.builtin.gallery_dl.source import _build_gallery_dl_config

    await _build_gallery_dl_config({})
    config = json.loads(mock_config_path.read_text())
    assert config["extractor"]["module-sources"] == [str(bundled_dir), None]


# ── load_inprocess ──


def test_load_inprocess_registers_bundled_module(bundled_dir, fake_gallery_dl):
    _write_extractor(bundled_dir, "gdlx_registers")
    try:
        assert _extractors.load_inprocess() == ["gdlx_registers"]
        assert fake_gallery_dl.add_module.call_count == 1
        assert fake_gallery_dl.add_module.call_args[0][0].__name__ == "gdlx_registers"
    finally:
        sys.modules.pop("gdlx_registers", None)


def test_load_inprocess_does_not_reregister_on_repeated_init(bundled_dir, fake_gallery_dl):
    """init_plugins() runs several times per process; add_module does not deduplicate."""
    _write_extractor(bundled_dir, "gdlx_idempotent")
    try:
        assert _extractors.load_inprocess() == ["gdlx_idempotent"]
        assert _extractors.load_inprocess() == []
        assert fake_gallery_dl.add_module.call_count == 1
    finally:
        sys.modules.pop("gdlx_idempotent", None)


def test_load_inprocess_survives_extractor_raising_on_import(bundled_dir, fake_gallery_dl):
    """A broken extractor must not take down API/worker startup."""
    _write_extractor(bundled_dir, "gdlx_broken", body="raise RuntimeError('boom')\n")
    try:
        assert _extractors.load_inprocess() == []
        fake_gallery_dl.add_module.assert_not_called()
    finally:
        sys.modules.pop("gdlx_broken", None)


def test_load_inprocess_loads_healthy_module_despite_broken_sibling(bundled_dir, fake_gallery_dl):
    _write_extractor(bundled_dir, "gdlx_sibling_bad", body="raise RuntimeError('boom')\n")
    _write_extractor(bundled_dir, "gdlx_sibling_ok")
    try:
        assert _extractors.load_inprocess() == ["gdlx_sibling_ok"]
    finally:
        sys.modules.pop("gdlx_sibling_bad", None)
        sys.modules.pop("gdlx_sibling_ok", None)


def test_load_inprocess_returns_empty_without_gallery_dl_installed(bundled_dir, monkeypatch):
    """gallery-dl lives in the image/venv, not in every environment that imports this."""
    _write_extractor(bundled_dir, "gdlx_no_gdl")
    monkeypatch.setitem(sys.modules, "gallery_dl", None)
    try:
        assert _extractors.load_inprocess() == []
    finally:
        sys.modules.pop("gdlx_no_gdl", None)


def test_load_inprocess_no_op_when_nothing_bundled(bundled_dir, fake_gallery_dl):
    assert _extractors.load_inprocess() == []
    fake_gallery_dl.add_module.assert_not_called()


def test_load_inprocess_leaves_sys_path_clean(bundled_dir, fake_gallery_dl):
    """The bundled dir is only on sys.path during import — it must not linger."""
    _write_extractor(bundled_dir, "gdlx_syspath")
    before = list(sys.path)
    try:
        _extractors.load_inprocess()
        assert sys.path == before
    finally:
        sys.modules.pop("gdlx_syspath", None)
