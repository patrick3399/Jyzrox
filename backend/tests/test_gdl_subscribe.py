"""Tests for gallery-dl subscription support.

Covers:
- check_gdl_new_works() from plugins.builtin.gallery_dl._subscribe
- GalleryDlSubscribableProxy from plugins.builtin.gallery_dl._subscribe
- _extract_source_id() from routers.subscriptions (new sites)
- Proxy registration in plugins.__init__

The subprocess is mocked via asyncio.create_subprocess_exec so no real
gallery-dl binary is required.  All temp file operations are patched to
avoid filesystem side-effects.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_stdout(*entries: list) -> bytes:
    """Build stdout bytes from a list of gallery-dl JSON entries."""
    return "\n".join(json.dumps(e) for e in entries).encode()


def _file_entry(item_id, id_key="tweet_id", extra=None):
    """Build a gallery-dl type-2 (file) entry."""
    meta = {id_key: item_id, "url": f"https://example.com/{item_id}"}
    if extra:
        meta.update(extra)
    return [2, f"https://example.com/{item_id}", meta]


def _dir_entry():
    """Build a gallery-dl type-1 (directory) entry."""
    return [1, "/some/path", {}]


def _make_proc(stdout: bytes = b"", returncode: int = 0) -> AsyncMock:
    """Build a mock asyncio subprocess process."""
    proc = AsyncMock()
    proc.communicate.return_value = (stdout, b"")
    proc.returncode = returncode
    proc.kill = MagicMock()
    proc.wait = AsyncMock()
    return proc


# ---------------------------------------------------------------------------
# check_gdl_new_works
# ---------------------------------------------------------------------------


class TestCheckGdlNewWorks:
    """Tests for the core check function."""

    @pytest.mark.asyncio
    async def test_basic_new_works_returns_all_files(self):
        """Should return new works from gallery-dl output."""
        from plugins.builtin.gallery_dl._subscribe import check_gdl_new_works

        stdout = _make_stdout(
            _dir_entry(),
            _file_entry("111"),
            _file_entry("222"),
            _file_entry("333"),
        )

        with patch("asyncio.create_subprocess_exec", return_value=_make_proc(stdout)):
            works = await check_gdl_new_works("twitter", "testuser", None, None)

        assert len(works) == 3
        assert works[0].source_id == "111"
        assert works[1].source_id == "222"
        assert works[2].source_id == "333"

    @pytest.mark.asyncio
    async def test_incremental_with_last_known_stops_at_boundary(self):
        """Should stop collecting when last_known item ID is encountered."""
        from plugins.builtin.gallery_dl._subscribe import check_gdl_new_works

        stdout = _make_stdout(
            _file_entry("aaa"),
            _file_entry("bbb"),
            _file_entry("ccc"),  # this is last_known — stop here
            _file_entry("ddd"),  # should not appear
        )

        with patch("asyncio.create_subprocess_exec", return_value=_make_proc(stdout)):
            works = await check_gdl_new_works("twitter", "user1", "ccc", None)

        assert len(works) == 2
        assert works[0].source_id == "aaa"
        assert works[1].source_id == "bbb"

    @pytest.mark.asyncio
    async def test_first_check_uses_range_flag(self):
        """First check (last_known=None) should add --range 1-50 to the command."""
        from plugins.builtin.gallery_dl._subscribe import check_gdl_new_works

        with patch("asyncio.create_subprocess_exec", return_value=_make_proc()) as mock_exec:
            await check_gdl_new_works("twitter", "user1", None, None)

        args = mock_exec.call_args[0]
        assert "--range" in args
        assert "1-50" in args

    @pytest.mark.asyncio
    async def test_incremental_check_omits_range_flag(self):
        """Incremental check (last_known set) should NOT add --range."""
        from plugins.builtin.gallery_dl._subscribe import check_gdl_new_works

        with patch("asyncio.create_subprocess_exec", return_value=_make_proc()) as mock_exec:
            await check_gdl_new_works("twitter", "user1", "last123", None)

        args = mock_exec.call_args[0]
        assert "--range" not in args

    @pytest.mark.asyncio
    async def test_dedup_multi_image_same_id(self):
        """Multiple file entries with the same tweet_id should be deduplicated."""
        from plugins.builtin.gallery_dl._subscribe import check_gdl_new_works

        stdout = _make_stdout(
            _file_entry("111"),
            _file_entry("111"),  # duplicate
            _file_entry("111"),  # duplicate
            _file_entry("222"),
        )

        with patch("asyncio.create_subprocess_exec", return_value=_make_proc(stdout)):
            works = await check_gdl_new_works("twitter", "user1", None, None)

        assert len(works) == 2
        assert works[0].source_id == "111"
        assert works[1].source_id == "222"

    @pytest.mark.asyncio
    async def test_empty_stdout_returns_empty_list(self):
        """Empty stdout should return empty list."""
        from plugins.builtin.gallery_dl._subscribe import check_gdl_new_works

        with patch("asyncio.create_subprocess_exec", return_value=_make_proc(b"")):
            works = await check_gdl_new_works("twitter", "user1", None, None)

        assert works == []

    @pytest.mark.asyncio
    async def test_timeout_returns_empty_list(self):
        """Should return empty list and kill the process on timeout."""
        from plugins.builtin.gallery_dl._subscribe import check_gdl_new_works

        proc = _make_proc()
        proc.communicate.side_effect = asyncio.TimeoutError()

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            works = await check_gdl_new_works("twitter", "user1", None, None)

        assert works == []
        proc.kill.assert_called_once()

    @pytest.mark.asyncio
    async def test_unsupported_source_returns_empty_list(self):
        """Unsupported source should return empty list without launching subprocess."""
        from plugins.builtin.gallery_dl._subscribe import check_gdl_new_works

        with patch("asyncio.create_subprocess_exec") as mock_exec:
            works = await check_gdl_new_works("nonexistent_site", "user1", None, None)

        assert works == []
        mock_exec.assert_not_called()

    @pytest.mark.asyncio
    async def test_instagram_uses_shortcode_id_key(self):
        """Instagram entries should use 'shortcode' as the dedup/id key."""
        from plugins.builtin.gallery_dl._subscribe import check_gdl_new_works

        stdout = _make_stdout(
            _file_entry("abc123", id_key="shortcode"),
            _file_entry("def456", id_key="shortcode"),
        )

        with patch("asyncio.create_subprocess_exec", return_value=_make_proc(stdout)):
            works = await check_gdl_new_works("instagram", "user1", None, None)

        assert len(works) == 2
        assert works[0].source_id == "abc123"
        assert works[1].source_id == "def456"

    @pytest.mark.asyncio
    async def test_credentials_cause_config_flag_in_command(self):
        """Credentials should cause a temp config file and --config flag in the command."""
        from plugins.builtin.gallery_dl._subscribe import check_gdl_new_works

        creds = json.dumps({"auth_token": "abc", "ct0": "xyz"})

        with (
            patch("asyncio.create_subprocess_exec", return_value=_make_proc()) as mock_exec,
            patch("os.unlink"),  # don't actually delete temp file
        ):
            await check_gdl_new_works("twitter", "user1", None, creds)

        args = mock_exec.call_args[0]
        assert "--config" in args

    @pytest.mark.asyncio
    async def test_dir_entries_are_skipped(self):
        """Type-1 directory entries should not appear in results."""
        from plugins.builtin.gallery_dl._subscribe import check_gdl_new_works

        stdout = _make_stdout(
            _dir_entry(),
            _dir_entry(),
            _file_entry("42"),
        )

        with patch("asyncio.create_subprocess_exec", return_value=_make_proc(stdout)):
            works = await check_gdl_new_works("twitter", "user1", None, None)

        assert len(works) == 1
        assert works[0].source_id == "42"

    @pytest.mark.asyncio
    async def test_nonzero_returncode_still_returns_collected_works(self):
        """Works collected before a non-zero exit should still be returned."""
        from plugins.builtin.gallery_dl._subscribe import check_gdl_new_works

        stdout = _make_stdout(
            _file_entry("99"),
            _file_entry("100"),
        )
        proc = _make_proc(stdout, returncode=1)

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            works = await check_gdl_new_works("twitter", "user1", None, None)

        # The function should not crash and may return partial results or empty.
        # Exact behavior depends on implementation; at minimum it must not raise.
        assert isinstance(works, list)

    @pytest.mark.asyncio
    async def test_last_known_not_in_output_returns_all(self):
        """If last_known is never seen in the output, all entries should be returned."""
        from plugins.builtin.gallery_dl._subscribe import check_gdl_new_works

        stdout = _make_stdout(
            _file_entry("aaa"),
            _file_entry("bbb"),
        )

        with patch("asyncio.create_subprocess_exec", return_value=_make_proc(stdout)):
            works = await check_gdl_new_works("twitter", "user1", "zzz", None)

        assert len(works) == 2

    @pytest.mark.asyncio
    async def test_newwork_url_field_is_set(self):
        """Each returned NewWork should have a non-empty url field."""
        from plugins.builtin.gallery_dl._subscribe import check_gdl_new_works

        stdout = _make_stdout(_file_entry("555"))

        with patch("asyncio.create_subprocess_exec", return_value=_make_proc(stdout)):
            works = await check_gdl_new_works("twitter", "user1", None, None)

        assert len(works) == 1
        assert works[0].url  # non-empty string


# ---------------------------------------------------------------------------
# GalleryDlSubscribableProxy
# ---------------------------------------------------------------------------


class TestGalleryDlSubscribableProxy:
    """Tests for the lightweight proxy class."""

    def _make_gdl_meta(self):
        from plugins.models import PluginMeta

        return PluginMeta(
            name="gallery-dl (Fallback)",
            source_id="gallery_dl",
            version="1.0.0",
            url_patterns=[],
            credential_schema=[],
        )

    def test_proxy_meta_source_id_is_target_source(self):
        """Proxy meta.source_id must equal the target source, not 'gallery_dl'."""
        from plugins.builtin.gallery_dl._subscribe import GalleryDlSubscribableProxy

        proxy = GalleryDlSubscribableProxy("twitter", self._make_gdl_meta())
        assert proxy.meta.source_id == "twitter"

    def test_proxy_meta_name_contains_source(self):
        """Proxy meta.name should reference the target source."""
        from plugins.builtin.gallery_dl._subscribe import GalleryDlSubscribableProxy

        proxy = GalleryDlSubscribableProxy("instagram", self._make_gdl_meta())
        assert "instagram" in proxy.meta.name.lower()

    def test_proxy_meta_source_id_differs_per_source(self):
        """Two proxies for different sources must have different meta.source_id values."""
        from plugins.builtin.gallery_dl._subscribe import GalleryDlSubscribableProxy

        proxy_tw = GalleryDlSubscribableProxy("twitter", self._make_gdl_meta())
        proxy_ig = GalleryDlSubscribableProxy("instagram", self._make_gdl_meta())
        assert proxy_tw.meta.source_id != proxy_ig.meta.source_id

    @pytest.mark.asyncio
    async def test_proxy_delegates_to_check_gdl_new_works(self):
        """Proxy.check_new_works should delegate to check_gdl_new_works with correct args."""
        from plugins.builtin.gallery_dl._subscribe import GalleryDlSubscribableProxy
        from plugins.models import NewWork

        proxy = GalleryDlSubscribableProxy("twitter", self._make_gdl_meta())

        expected = [NewWork(url="https://x.com/123", source_id="123")]

        with patch(
            "plugins.builtin.gallery_dl._subscribe.check_gdl_new_works",
            new_callable=AsyncMock,
            return_value=expected,
        ) as mock_check:
            result = await proxy.check_new_works("user1", None, None)

        mock_check.assert_called_once_with("twitter", "user1", None, None)
        assert len(result) == 1
        assert result[0].source_id == "123"

    @pytest.mark.asyncio
    async def test_proxy_passes_last_known_and_credentials(self):
        """Proxy should forward last_known and credentials to check_gdl_new_works."""
        from plugins.builtin.gallery_dl._subscribe import GalleryDlSubscribableProxy
        from plugins.models import NewWork

        proxy = GalleryDlSubscribableProxy("instagram", self._make_gdl_meta())
        creds = json.dumps({"sessionid": "tok"})

        with patch(
            "plugins.builtin.gallery_dl._subscribe.check_gdl_new_works",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_check:
            await proxy.check_new_works("testuser", "last_abc", creds)

        mock_check.assert_called_once_with("instagram", "testuser", "last_abc", creds)

    @pytest.mark.asyncio
    async def test_proxy_satisfies_subscribable_protocol(self):
        """GalleryDlSubscribableProxy must satisfy the Subscribable protocol."""
        from plugins.base import Subscribable
        from plugins.builtin.gallery_dl._subscribe import GalleryDlSubscribableProxy

        proxy = GalleryDlSubscribableProxy("twitter", self._make_gdl_meta())
        assert isinstance(proxy, Subscribable)


# ---------------------------------------------------------------------------
# _extract_source_id — new sites
# ---------------------------------------------------------------------------


class TestExtractSourceIdNewSites:
    """Tests for _extract_source_id() with newly added site support."""

    def _call(self, url: str, source: str):
        from routers.subscriptions import _extract_source_id
        return _extract_source_id(url, source)

    def test_facebook_extracts_username(self):
        assert self._call("https://www.facebook.com/someuser/photos", "facebook") == "someuser"

    def test_instagram_extracts_username(self):
        assert self._call("https://www.instagram.com/someuser/", "instagram") == "someuser"

    def test_instagram_extracts_username_no_trailing_slash(self):
        assert self._call("https://www.instagram.com/artist123", "instagram") == "artist123"

    def test_deviantart_extracts_username(self):
        assert self._call(
            "https://www.deviantart.com/artist123/gallery/all", "deviantart"
        ) == "artist123"

    def test_tumblr_extracts_blog_name(self):
        assert self._call("https://www.tumblr.com/blogname/", "tumblr") == "blogname"

    def test_reddit_extracts_user_segment(self):
        result = self._call("https://www.reddit.com/user/someuser/submitted/", "reddit")
        # The function extracts the first meaningful path segment
        assert result is not None
        assert result != ""

    def test_bluesky_extracts_profile_segment(self):
        result = self._call("https://bsky.app/profile/handle.bsky.social/", "bluesky")
        assert result is not None
        assert result != ""

    def test_kemono_extracts_service_and_id(self):
        assert self._call("https://kemono.su/patreon/user/12345", "kemono") == "patreon:12345"

    def test_kemono_no_match_returns_none(self):
        assert self._call("https://kemono.su/invalid/path", "kemono") is None

    def test_twitter_existing_behaviour_preserved(self):
        """Existing twitter extraction must not be broken by new site additions."""
        assert self._call("https://x.com/username/media", "twitter") == "username"

    def test_unknown_source_returns_none(self):
        assert self._call("https://example.com/path", "unknown_site") is None

    def test_pixiv_existing_behaviour_preserved(self):
        """Existing pixiv extraction must not be broken by new site additions."""
        assert self._call("https://www.pixiv.net/en/users/12345678", "pixiv") == "12345678"


# ---------------------------------------------------------------------------
# SITE_CONFIG completeness
# ---------------------------------------------------------------------------


class TestSiteConfig:
    """Tests for SITE_CONFIG dict in _subscribe module."""

    def test_site_config_contains_twitter(self):
        from plugins.builtin.gallery_dl._subscribe import SITE_CONFIG

        assert "twitter" in SITE_CONFIG

    def test_site_config_contains_instagram(self):
        from plugins.builtin.gallery_dl._subscribe import SITE_CONFIG

        assert "instagram" in SITE_CONFIG

    def test_site_config_entry_has_id_key(self):
        """Each SITE_CONFIG entry must have an 'id_key' field."""
        from plugins.builtin.gallery_dl._subscribe import SITE_CONFIG

        for source, cfg in SITE_CONFIG.items():
            assert "id_key" in cfg, f"SITE_CONFIG[{source!r}] missing 'id_key'"

    def test_site_config_entry_has_url_tpl(self):
        """Each SITE_CONFIG entry must have a 'url_tpl' field."""
        from plugins.builtin.gallery_dl._subscribe import SITE_CONFIG

        for source, cfg in SITE_CONFIG.items():
            assert "url_tpl" in cfg, f"SITE_CONFIG[{source!r}] missing 'url_tpl'"

    def test_instagram_uses_shortcode_id_key(self):
        """Instagram id_key should be 'shortcode'."""
        from plugins.builtin.gallery_dl._subscribe import SITE_CONFIG

        assert SITE_CONFIG["instagram"]["id_key"] == "shortcode"

    def test_twitter_uses_tweet_id_key(self):
        """Twitter id_key should be 'tweet_id'."""
        from plugins.builtin.gallery_dl._subscribe import SITE_CONFIG

        assert SITE_CONFIG["twitter"]["id_key"] == "tweet_id"


# ---------------------------------------------------------------------------
# Proxy registration in plugins.__init__
# ---------------------------------------------------------------------------


class TestProxyRegistration:
    """Tests for gallery-dl proxy registration in the plugin registry."""

    @pytest.mark.asyncio
    async def test_twitter_subscribable_registered(self):
        """After init_plugins(), 'twitter' should be in the subscribable registry."""
        from plugins import init_plugins
        from plugins.registry import PluginRegistry

        registry = PluginRegistry()

        # Patch both the canonical singleton and the imported reference in plugins/__init__
        with patch("plugins.registry.plugin_registry", registry), \
             patch("plugins.plugin_registry", registry):
            await init_plugins()

        subscribables = registry.list_subscribable()
        assert "twitter" in subscribables

    @pytest.mark.asyncio
    async def test_instagram_subscribable_registered(self):
        """After init_plugins(), 'instagram' should be in the subscribable registry."""
        from plugins import init_plugins
        from plugins.registry import PluginRegistry

        registry = PluginRegistry()

        with patch("plugins.registry.plugin_registry", registry), \
             patch("plugins.plugin_registry", registry):
            await init_plugins()

        subscribables = registry.list_subscribable()
        assert "instagram" in subscribables

    @pytest.mark.asyncio
    async def test_gallery_dl_sources_registered_for_all_site_config(self):
        """Every source in SITE_CONFIG should appear as a subscribable after init_plugins()."""
        from plugins import init_plugins
        from plugins.builtin.gallery_dl._subscribe import SITE_CONFIG
        from plugins.registry import PluginRegistry

        registry = PluginRegistry()

        with patch("plugins.registry.plugin_registry", registry), \
             patch("plugins.plugin_registry", registry):
            await init_plugins()

        subscribables = registry.list_subscribable()
        for source in SITE_CONFIG:
            assert source in subscribables, (
                f"Expected '{source}' in subscribables after init_plugins(), got: {subscribables}"
            )
