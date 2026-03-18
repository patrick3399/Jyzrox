"""Tests for gallery-dl config generation and fragment detection."""

import json
from unittest.mock import patch

import pytest

from plugins.builtin.gallery_dl.source import _is_fragment


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
        mock_settings.data_archive_path = str(tmp_path / "archive")
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
