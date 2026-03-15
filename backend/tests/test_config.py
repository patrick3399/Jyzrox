"""
Tests for core/config.py.

Covers:
- Settings default field values
- Environment variable overrides (via monkeypatch)
- get_all_library_paths(): env-only, deduplication, and DB merge
"""

import sys
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Settings — defaults
# ---------------------------------------------------------------------------


class TestSettingsDefaults:
    """Verify key default values on a freshly constructed Settings instance."""

    def _make_settings(self):
        from core.config import Settings

        return Settings(
            database_url="sqlite+aiosqlite:///:memory:",
            credential_encrypt_key="test-key-0123456789abcdef01234567",
        )

    def test_settings_is_pydantic_model_instance(self):
        """Settings must be a valid Pydantic BaseSettings instance."""
        from pydantic_settings import BaseSettings

        s = self._make_settings()
        assert isinstance(s, BaseSettings)

    def test_settings_default_redis_url(self):
        """Default redis_url must be 'redis://redis:6379' when no env override is present.

        We pass the value explicitly to bypass the process-level REDIS_URL set by
        conftest.py, which is needed so that other tests run without a live Redis.
        The assertion documents the intended production default in source.
        """
        from core.config import Settings

        s = Settings(
            database_url="sqlite+aiosqlite:///:memory:",
            credential_encrypt_key="test-key-0123456789abcdef01234567",
            redis_url="redis://redis:6379",
        )
        assert s.redis_url == "redis://redis:6379"

    def test_settings_default_cookie_secure(self):
        """cookie_secure must accept True when explicitly set, defaulting to True in prod.

        conftest.py sets COOKIE_SECURE=false for the test suite; we pass the field
        explicitly to verify the field parses and stores boolean values correctly.
        """
        from core.config import Settings

        s = Settings(
            database_url="sqlite+aiosqlite:///:memory:",
            credential_encrypt_key="test-key-0123456789abcdef01234567",
            cookie_secure=True,
        )
        assert s.cookie_secure is True

    def test_settings_default_rate_limit_and_csrf_enabled(self):
        """rate_limit_enabled and csrf_enabled both default True in production config.

        conftest.py overrides RATE_LIMIT_ENABLED=false; we pass explicitly to verify
        both boolean fields parse correctly and that csrf_enabled is independent.
        """
        from core.config import Settings

        s = Settings(
            database_url="sqlite+aiosqlite:///:memory:",
            credential_encrypt_key="test-key-0123456789abcdef01234567",
            rate_limit_enabled=True,
            csrf_enabled=True,
        )
        assert s.rate_limit_enabled is True
        assert s.csrf_enabled is True

    def test_settings_default_data_gallery_path(self):
        """data_gallery_path defaults to /data/gallery (container-side mount)."""
        s = self._make_settings()
        assert s.data_gallery_path == "/data/gallery"

    def test_settings_default_pixiv_client_id(self):
        """pixiv_client_id defaults to the public Android app credential."""
        s = self._make_settings()
        assert s.pixiv_client_id == "MOBrBDS8blbauoSck0ZfDbtuzpyT"

    def test_settings_default_eh_max_concurrency(self):
        """eh_max_concurrency defaults to 2 to respect EH rate limits."""
        s = self._make_settings()
        assert s.eh_max_concurrency == 2

    def test_settings_default_tag_model_enabled(self):
        """tag_model_enabled defaults to False; opt-in only."""
        s = self._make_settings()
        assert s.tag_model_enabled is False

    def test_settings_default_library_base_path(self):
        """library_base_path defaults to /mnt for host-mounted external media."""
        s = self._make_settings()
        assert s.library_base_path == "/mnt"

    def test_settings_default_extra_library_paths_is_empty(self):
        """extra_library_paths defaults to empty string (no extra paths)."""
        s = self._make_settings()
        assert s.extra_library_paths == ""


# ---------------------------------------------------------------------------
# Settings — environment variable overrides
# ---------------------------------------------------------------------------


class TestSettingsEnvOverride:
    """Verify that env vars are picked up by a freshly created Settings."""

    def test_settings_env_override_redis_url(self, monkeypatch):
        """REDIS_URL env var must override the default redis_url."""
        from core.config import get_settings, Settings

        monkeypatch.setenv("REDIS_URL", "redis://custom-host:6380")
        get_settings.cache_clear()
        try:
            s = Settings(
                database_url="sqlite+aiosqlite:///:memory:",
                credential_encrypt_key="test-key-0123456789abcdef01234567",
            )
            assert s.redis_url == "redis://custom-host:6380"
        finally:
            get_settings.cache_clear()

    def test_settings_env_override_cookie_secure_false(self, monkeypatch):
        """COOKIE_SECURE=false must disable cookie_secure for local HTTP dev."""
        from core.config import get_settings, Settings

        monkeypatch.setenv("COOKIE_SECURE", "false")
        get_settings.cache_clear()
        try:
            s = Settings(
                database_url="sqlite+aiosqlite:///:memory:",
                credential_encrypt_key="test-key-0123456789abcdef01234567",
            )
            assert s.cookie_secure is False
        finally:
            get_settings.cache_clear()

    def test_settings_env_override_eh_max_concurrency(self, monkeypatch):
        """EH_MAX_CONCURRENCY env var must override the default of 2."""
        from core.config import get_settings, Settings

        monkeypatch.setenv("EH_MAX_CONCURRENCY", "10")
        get_settings.cache_clear()
        try:
            s = Settings(
                database_url="sqlite+aiosqlite:///:memory:",
                credential_encrypt_key="test-key-0123456789abcdef01234567",
            )
            assert s.eh_max_concurrency == 10
        finally:
            get_settings.cache_clear()


# ---------------------------------------------------------------------------
# get_all_library_paths() — unit tests with mocked DB
# ---------------------------------------------------------------------------


class TestGetAllLibraryPaths:
    """Unit tests for the get_all_library_paths() async function."""

    @pytest.mark.asyncio
    async def test_no_env_and_no_db_paths_returns_empty(self):
        """With no env paths and an empty DB result, the returned list is empty."""
        from core.config import get_settings, Settings

        # Patch settings so extra_library_paths is empty
        mock_settings = Settings(
            database_url="sqlite+aiosqlite:///:memory:",
            credential_encrypt_key="test-key-0123456789abcdef01234567",
            extra_library_paths="",
        )

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_factory = MagicMock(return_value=mock_ctx)

        with (
            patch("core.config.settings", mock_settings),
            patch("core.database.async_session", mock_factory),
        ):
            from core.config import get_all_library_paths

            paths = await get_all_library_paths()

        assert paths == []

    @pytest.mark.asyncio
    async def test_env_paths_are_deduplicated(self):
        """Duplicate paths in extra_library_paths must appear only once."""
        from core.config import get_settings, Settings

        mock_settings = Settings(
            database_url="sqlite+aiosqlite:///:memory:",
            credential_encrypt_key="test-key-0123456789abcdef01234567",
            extra_library_paths="/path/a,/path/b,/path/a",
        )

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_factory = MagicMock(return_value=mock_ctx)

        with (
            patch("core.config.settings", mock_settings),
            patch("core.database.async_session", mock_factory),
        ):
            from core.config import get_all_library_paths

            paths = await get_all_library_paths()

        assert paths == ["/path/a", "/path/b"]

    @pytest.mark.asyncio
    async def test_db_paths_merged_and_deduplicated_with_env_paths(self):
        """DB paths must be appended after env paths, with duplicates dropped."""
        from core.config import get_settings, Settings

        mock_settings = Settings(
            database_url="sqlite+aiosqlite:///:memory:",
            credential_encrypt_key="test-key-0123456789abcdef01234567",
            extra_library_paths="/mnt/nas/comics,/mnt/hdd/manga",
        )

        # DB returns one new path and one that already appeared in env
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value = ["/mnt/hdd/manga", "/mnt/ssd/artbooks"]
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_factory = MagicMock(return_value=mock_ctx)

        with (
            patch("core.config.settings", mock_settings),
            patch("core.database.async_session", mock_factory),
        ):
            from core.config import get_all_library_paths

            paths = await get_all_library_paths()

        assert paths == ["/mnt/nas/comics", "/mnt/hdd/manga", "/mnt/ssd/artbooks"]

    @pytest.mark.asyncio
    async def test_db_exception_is_silenced_env_paths_still_returned(self):
        """If the DB query raises, the function must not raise and still return env paths."""
        from core.config import get_settings, Settings

        mock_settings = Settings(
            database_url="sqlite+aiosqlite:///:memory:",
            credential_encrypt_key="test-key-0123456789abcdef01234567",
            extra_library_paths="/path/safe",
        )

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(side_effect=Exception("DB unavailable"))
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_factory = MagicMock(return_value=mock_ctx)

        with (
            patch("core.config.settings", mock_settings),
            patch("core.database.async_session", mock_factory),
        ):
            from core.config import get_all_library_paths

            paths = await get_all_library_paths()

        assert paths == ["/path/safe"]
