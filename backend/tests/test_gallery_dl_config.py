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
async def test_v3_sleep_429_uses_exponential_backoff_not_fixed(mock_config_path):
    """Regression: fixed sleep-429=60 / sleep-retries=10 re-hit rate-limited
    sites at a constant interval. Use gallery-dl's exp duration syntax
    (exp:BASE:START:MAX=VALUE -> min(START + VALUE*BASE^(n-1), MAX)).
    """
    from plugins.builtin.gallery_dl.source import _build_gallery_dl_config

    await _build_gallery_dl_config({})
    config = json.loads(mock_config_path.read_text())
    assert config["extractor"]["sleep-429"] == "exp:2:0:300=30"
    assert config["extractor"]["sleep-retries"] == "exp:2:0:120=5"


@pytest.mark.asyncio
async def test_v3_eh_has_conservative_backoff_override(mock_config_path):
    """EH 429s are ban-adjacent — back off harder than the global default.
    gallery-dl runs both EH domains under the 'exhentai' category.
    """
    from plugins.builtin.gallery_dl.source import _build_gallery_dl_config

    await _build_gallery_dl_config({})
    config = json.loads(mock_config_path.read_text())
    for cat in ("exhentai", "e-hentai"):
        assert config["extractor"][cat]["sleep-429"] == "exp:2:0:600=60"
        assert config["extractor"][cat]["sleep-retries"] == "exp:2:0:300=10"


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
    # date-after should be 1 day before last_completed_at (buffer for timezone edge cases)
    assert config["extractor"]["date-after"] == "2026-03-14T08:00:00"


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
async def test_v3_cookie_update_is_writeback_path_not_true(mock_config_path):
    """cookies-update must be the file path the worker's cookie writeback reads.

    Regression: config wrote cookies-update=True, which gallery-dl treats as
    "rewrite the input cookies file" — a no-op when cookies are passed inline
    as a dict. Meanwhile _writeback_cookies() waited for
    /tmp/gdl-cookies-{job}-{src}.txt that nothing wrote, so refreshed session
    cookies were never persisted back to the DB.
    """
    from plugins.builtin.gallery_dl.source import _build_gallery_dl_config

    path = await _build_gallery_dl_config(
        {"ehentai": '{"ipb_member_id": "1", "ipb_pass_hash": "x"}'}, config_id="job-123"
    )
    config = json.loads(path.read_text())
    expected = "/tmp/gdl-cookies-job-123-ehentai.txt"
    assert config["extractor"]["ehentai"]["cookies-update"] == expected
    # EH downloads run under the exhentai/e-hentai extractor categories,
    # so the export path must be set there too.
    assert config["extractor"]["exhentai"]["cookies-update"] == expected
    assert config["extractor"]["e-hentai"]["cookies-update"] == expected


@pytest.mark.asyncio
async def test_v3_cookie_update_fragment_format_gets_path(mock_config_path):
    """Fragment-format cookie credentials get the same writeback path."""
    from plugins.builtin.gallery_dl.source import _build_gallery_dl_config

    path = await _build_gallery_dl_config({"twitter": '{"cookies": {"auth_token": "abc"}}'}, config_id="job-456")
    config = json.loads(path.read_text())
    assert config["extractor"]["twitter"]["cookies-update"] == "/tmp/gdl-cookies-job-456-twitter.txt"


@pytest.mark.asyncio
async def test_v3_cookie_update_omitted_without_config_id(mock_config_path):
    """Without a job-scoped config_id there is no writeback reader — omit the option."""
    from plugins.builtin.gallery_dl.source import _build_gallery_dl_config

    await _build_gallery_dl_config({"ehentai": '{"ipb_member_id": "1", "ipb_pass_hash": "x"}'})
    config = json.loads(mock_config_path.read_text())
    assert "cookies-update" not in config["extractor"]["ehentai"]


@pytest.mark.asyncio
async def test_v3_rate_limit_of_other_site_does_not_leak_into_job(mock_config_path, mock_site_config_service):
    """Regression: any site's rate_limit was written into the global
    downloader.rate (last-wins over GDL_SITES order), so e.g. a pixiv
    bandwidth cap silently throttled ehentai downloads too.
    """
    from core.site_config import DownloadParams
    from plugins.builtin.gallery_dl.source import _build_gallery_dl_config

    mock_site_config_service.get_all_download_params.return_value = {
        "pixiv": DownloadParams(rate_limit="500k"),
    }
    await _build_gallery_dl_config({}, target_source_id="ehentai")
    config = json.loads(mock_config_path.read_text())
    assert "rate" not in config.get("downloader", {})


@pytest.mark.asyncio
async def test_v3_rate_limit_applies_when_site_is_target(mock_config_path, mock_site_config_service):
    from core.site_config import DownloadParams
    from plugins.builtin.gallery_dl.source import _build_gallery_dl_config

    mock_site_config_service.get_all_download_params.return_value = {
        "pixiv": DownloadParams(rate_limit="500k"),
    }
    await _build_gallery_dl_config({}, target_source_id="pixiv")
    config = json.loads(mock_config_path.read_text())
    assert config["downloader"]["rate"] == "500k"


@pytest.mark.asyncio
async def test_v3_no_rate_limit_without_target_site(mock_config_path, mock_site_config_service):
    """Without a resolved target site no bandwidth cap should be applied."""
    from core.site_config import DownloadParams
    from plugins.builtin.gallery_dl.source import _build_gallery_dl_config

    mock_site_config_service.get_all_download_params.return_value = {
        "pixiv": DownloadParams(rate_limit="500k"),
    }
    await _build_gallery_dl_config({})
    config = json.loads(mock_config_path.read_text())
    assert "rate" not in config.get("downloader", {})


@pytest.mark.asyncio
async def test_v3_cookie_update_path_matches_worker_writeback_path(mock_config_path):
    """The config-side path helper and the worker reader must agree on the path."""
    from plugins.builtin.gallery_dl._sites import cookie_writeback_path

    assert str(cookie_writeback_path("j1", "ehentai")) == "/tmp/gdl-cookies-j1-ehentai.txt"


@pytest.mark.asyncio
async def test_v3_full_config_integration(mock_config_path):
    """Verify complete v3.0 config output with all features enabled."""
    from datetime import UTC, datetime

    from plugins.builtin.gallery_dl.source import _build_gallery_dl_config

    last = datetime(2026, 3, 15, 8, 0, 0, tzinfo=UTC)
    credentials = {
        "ehentai": '{"cookies": {"ipb_member_id": "1"}}',
        "pixiv": "refresh_token_123",
    }
    config_path = await _build_gallery_dl_config(
        credentials,
        config_id="test-job-123",
        job_context="subscription",
        last_completed_at=last,
    )

    config = json.loads(config_path.read_text())

    # N1: PostgreSQL archive (CASCADE tables, no format override)
    assert config["extractor"]["archive"].startswith("postgresql://")
    assert config["extractor"]["archive-table"] == "{category}"
    assert "archive-format" not in config["extractor"]

    # N10a: subscription has archive-mode memory
    assert config["extractor"]["archive-mode"] == "memory"

    # N10b: file-unique
    assert config["extractor"]["file-unique"] is True

    # N2: subscription optimization
    assert config["extractor"]["skip"] == "abort:10"
    assert "date-after" in config["extractor"]

    # N3: native rate limiting
    assert "sleep-429" in config["extractor"]
    assert "sleep-retries" in config["extractor"]

    # N4: content integrity
    assert config["extractor"]["filesize-min"] == "1k"
    assert config["downloader"]["adjust-extensions"] is True

    # N5: postprocessors
    pp_names = [pp["name"] for pp in config["postprocessors"]]
    assert "hash" in pp_names
    assert "mtime" in pp_names

    # N10d: metadata PP with include filter (replaces --write-metadata)
    assert "metadata" in pp_names
    meta_pp = next(pp for pp in config["postprocessors"] if pp["name"] == "metadata")
    assert "include" in meta_pp
    assert "title" in meta_pp["include"]
    assert "tags" in meta_pp["include"]

    # N6: ugoira (pixiv present in credentials)
    assert "ugoira" in pp_names

    # N8: cookies-update for EH (cookie-based auth) — job-scoped writeback path
    assert config["extractor"]["ehentai"].get("cookies-update") == "/tmp/gdl-cookies-test-job-123-ehentai.txt"

    # Credentials merged correctly
    assert config["extractor"]["ehentai"]["cookies"] == {"ipb_member_id": "1"}
    assert config["extractor"]["pixiv"]["refresh-token"] == "refresh_token_123"
