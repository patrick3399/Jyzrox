"""Tests for gallery-dl config generation and fragment detection."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from plugins.builtin.gallery_dl.source import _is_fragment


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


# ── _is_fragment tests ──


def test_is_fragment_rejects_legacy_cookie_dict():
    """Legacy EH cookies: {"ipb_member_id": "1"} -> no fragment keys -> False."""
    assert _is_fragment('{"ipb_member_id": "1", "ipb_pass_hash": "x"}') is False


def test_is_fragment_rejects_plain_string():
    assert _is_fragment("plain_token") is False


def test_is_fragment_rejects_generic_cookie_dict():
    """Existing generic cookies like {"session": "abc"} -> no fragment keys -> False."""
    assert _is_fragment('{"session": "abc"}') is False


def test_is_fragment_accepts_cookies_fragment():
    assert _is_fragment('{"cookies": {"auth_token": "abc"}}') is True


def test_is_fragment_accepts_username_fragment():
    assert _is_fragment('{"username": "user1", "password": "pass1"}') is True


def test_is_fragment_accepts_refresh_token_fragment():
    assert _is_fragment('{"refresh-token": "token123"}') is True


def test_is_fragment_accepts_api_key_fragment():
    assert _is_fragment('{"api-key": "key123"}') is True


def test_is_fragment_rejects_empty_string():
    assert _is_fragment("") is False


def test_is_fragment_rejects_none():
    assert _is_fragment(None) is False


# ── _build_gallery_dl_config tests ──


@pytest.fixture
def mock_config_path(tmp_path):
    """Mock settings.gallery_dl_config to a temp file."""
    config_file = tmp_path / "gallery-dl.json"
    with patch("plugins.builtin.gallery_dl.source.settings") as mock_settings:
        mock_settings.data_gallery_path = "/data/gallery"
        mock_settings.gallery_dl_config = str(config_file)
        mock_settings.gdl_archive_dsn = "postgresql://test:test@localhost:5432/test"
        yield config_file


@pytest.mark.asyncio
async def test_legacy_cookie_format(mock_config_path):
    """EH cookies in legacy format should be injected as-is."""
    from plugins.builtin.gallery_dl.source import _build_gallery_dl_config

    credentials = {"ehentai": '{"ipb_member_id": "1", "ipb_pass_hash": "x"}'}
    await _build_gallery_dl_config(credentials)

    config = json.loads(mock_config_path.read_text())
    assert config["extractor"]["ehentai"]["cookies"] == {"ipb_member_id": "1", "ipb_pass_hash": "x"}
    # Should propagate to extra extractors
    assert config["extractor"]["exhentai"]["cookies"] == {"ipb_member_id": "1", "ipb_pass_hash": "x"}
    assert config["extractor"]["e-hentai"]["cookies"] == {"ipb_member_id": "1", "ipb_pass_hash": "x"}


@pytest.mark.asyncio
async def test_legacy_refresh_token(mock_config_path):
    """Pixiv refresh token in legacy format."""
    from plugins.builtin.gallery_dl.source import _build_gallery_dl_config

    credentials = {"pixiv": "my_token"}
    await _build_gallery_dl_config(credentials)

    config = json.loads(mock_config_path.read_text())
    assert config["extractor"]["pixiv"]["refresh-token"] == "my_token"


@pytest.mark.asyncio
async def test_new_fragment_cookies(mock_config_path):
    """New fragment format with cookies."""
    from plugins.builtin.gallery_dl.source import _build_gallery_dl_config

    credentials = {"twitter": '{"cookies": {"auth_token": "abc", "ct0": "xyz"}}'}
    await _build_gallery_dl_config(credentials)

    config = json.loads(mock_config_path.read_text())
    assert config["extractor"]["twitter"]["cookies"] == {"auth_token": "abc", "ct0": "xyz"}


@pytest.mark.asyncio
async def test_new_fragment_username_password(mock_config_path):
    """New fragment format with username/password."""
    from plugins.builtin.gallery_dl.source import _build_gallery_dl_config

    credentials = {"danbooru": '{"username": "user1", "password": "pass1"}'}
    await _build_gallery_dl_config(credentials)

    config = json.loads(mock_config_path.read_text())
    assert config["extractor"]["danbooru"]["username"] == "user1"
    assert config["extractor"]["danbooru"]["password"] == "pass1"


@pytest.mark.asyncio
async def test_fragment_propagates_to_extra_extractors(mock_config_path):
    """Fragment cookies should propagate to extra_extractors (e.g., exhentai, e-hentai)."""
    from plugins.builtin.gallery_dl.source import _build_gallery_dl_config

    credentials = {"ehentai": '{"cookies": {"ipb": "1"}}'}
    await _build_gallery_dl_config(credentials)

    config = json.loads(mock_config_path.read_text())
    assert config["extractor"]["exhentai"]["cookies"] == {"ipb": "1"}
    assert config["extractor"]["e-hentai"]["cookies"] == {"ipb": "1"}


@pytest.mark.asyncio
async def test_empty_value_skipped(mock_config_path):
    """Empty credential values should be skipped."""
    from plugins.builtin.gallery_dl.source import _build_gallery_dl_config

    credentials = {"twitter": ""}
    await _build_gallery_dl_config(credentials)

    config = json.loads(mock_config_path.read_text())
    assert "twitter" not in config["extractor"]


# ── v3.0 config tests ──


@pytest.mark.asyncio
async def test_v3_config_has_pg_archive(mock_config_path):
    from plugins.builtin.gallery_dl.source import _build_gallery_dl_config

    await _build_gallery_dl_config({})
    config = json.loads(mock_config_path.read_text())
    assert "archive" in config["extractor"]
    assert config["extractor"]["archive"].startswith("postgresql://")
    assert config["extractor"]["archive-table"] == "{category}"


@pytest.mark.asyncio
async def test_v3_config_has_native_rate_limiting(mock_config_path):
    from plugins.builtin.gallery_dl.source import _build_gallery_dl_config

    await _build_gallery_dl_config({})
    config = json.loads(mock_config_path.read_text())
    assert "sleep-429" in config["extractor"]
    assert "sleep-retries" in config["extractor"]


@pytest.mark.asyncio
async def test_v3_config_has_file_unique(mock_config_path):
    from plugins.builtin.gallery_dl.source import _build_gallery_dl_config

    await _build_gallery_dl_config({})
    config = json.loads(mock_config_path.read_text())
    assert config["extractor"]["file-unique"] is True


@pytest.mark.asyncio
async def test_v3_subscription_has_archive_mode_memory(mock_config_path):
    from plugins.builtin.gallery_dl.source import _build_gallery_dl_config

    await _build_gallery_dl_config({}, job_context="subscription")
    config = json.loads(mock_config_path.read_text())
    assert config["extractor"]["archive-mode"] == "memory"


@pytest.mark.asyncio
async def test_v3_manual_no_archive_mode_memory(mock_config_path):
    from plugins.builtin.gallery_dl.source import _build_gallery_dl_config

    await _build_gallery_dl_config({})
    config = json.loads(mock_config_path.read_text())
    assert "archive-mode" not in config["extractor"]


@pytest.mark.asyncio
async def test_v3_config_has_postprocessors(mock_config_path):
    from plugins.builtin.gallery_dl.source import _build_gallery_dl_config

    await _build_gallery_dl_config({})
    config = json.loads(mock_config_path.read_text())
    pp_names = [pp["name"] for pp in config.get("postprocessors", [])]
    assert "hash" in pp_names
    assert "mtime" in pp_names


@pytest.mark.asyncio
async def test_v3_metadata_pp_with_include_filter(mock_config_path):
    from plugins.builtin.gallery_dl.source import _build_gallery_dl_config

    await _build_gallery_dl_config({})
    config = json.loads(mock_config_path.read_text())
    meta_pps = [pp for pp in config["postprocessors"] if pp["name"] == "metadata"]
    assert len(meta_pps) == 1
    assert "include" in meta_pps[0]
    assert "title" in meta_pps[0]["include"]
    assert "tags" in meta_pps[0]["include"]


@pytest.mark.asyncio
async def test_v3_config_has_content_integrity(mock_config_path):
    from plugins.builtin.gallery_dl.source import _build_gallery_dl_config

    await _build_gallery_dl_config({})
    config = json.loads(mock_config_path.read_text())
    assert config["extractor"]["filesize-min"] == "1k"
    assert config["downloader"]["adjust-extensions"] is True


@pytest.mark.asyncio
async def test_v3_subscription_context_has_abort_and_date(mock_config_path):
    from datetime import UTC, datetime

    from plugins.builtin.gallery_dl.source import _build_gallery_dl_config

    last = datetime(2026, 3, 15, 8, 0, 0, tzinfo=UTC)
    await _build_gallery_dl_config({}, job_context="subscription", last_completed_at=last)
    config = json.loads(mock_config_path.read_text())
    assert config["extractor"]["skip"] == "abort:10"
    assert "date-after" in config["extractor"]


@pytest.mark.asyncio
async def test_v3_manual_context_no_abort(mock_config_path):
    from plugins.builtin.gallery_dl.source import _build_gallery_dl_config

    await _build_gallery_dl_config({})
    config = json.loads(mock_config_path.read_text())
    assert "skip" not in config["extractor"]


@pytest.mark.asyncio
async def test_v3_pixiv_has_ugoira_pp(mock_config_path):
    from plugins.builtin.gallery_dl.source import _build_gallery_dl_config

    await _build_gallery_dl_config({"pixiv": "token123"})
    config = json.loads(mock_config_path.read_text())
    pp_names = [pp["name"] for pp in config.get("postprocessors", [])]
    assert "ugoira" in pp_names


@pytest.mark.asyncio
async def test_v3_non_pixiv_no_ugoira(mock_config_path):
    from plugins.builtin.gallery_dl.source import _build_gallery_dl_config

    await _build_gallery_dl_config({"ehentai": '{"ipb_member_id": "1", "ipb_pass_hash": "x"}'})
    config = json.loads(mock_config_path.read_text())
    pp_names = [pp["name"] for pp in config.get("postprocessors", [])]
    assert "ugoira" not in pp_names


@pytest.mark.asyncio
async def test_v3_archive_format_not_overridden(mock_config_path):
    from plugins.builtin.gallery_dl.source import _build_gallery_dl_config

    await _build_gallery_dl_config({})
    config = json.loads(mock_config_path.read_text())
    assert "archive-format" not in config["extractor"]
    assert config["extractor"]["archive-table"] == "{category}"


@pytest.mark.asyncio
async def test_v3_cookie_source_has_cookies_update(mock_config_path):
    from plugins.builtin.gallery_dl.source import _build_gallery_dl_config

    await _build_gallery_dl_config({"ehentai": '{"ipb_member_id": "1", "ipb_pass_hash": "x"}'})
    config = json.loads(mock_config_path.read_text())
    assert config["extractor"]["ehentai"].get("cookies-update") is True
