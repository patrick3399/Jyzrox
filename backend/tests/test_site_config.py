"""Tests for SiteConfigService — M1."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.site_config import DownloadParams, SiteConfigService

# ── DownloadParams defaults ──────────────────────────────────────────


def test_download_params_defaults():
    p = DownloadParams()
    assert p.retries == 4
    assert p.http_timeout == 30
    assert p.sleep_request is None
    assert p.concurrency == 2
    assert p.inactivity_timeout == 300


# ── Merge priority: override > adaptive > _sites.py defaults ─────────


@pytest.mark.asyncio
async def test_get_effective_params_returns_site_defaults_when_no_db_row():
    """No DB row → _sites.py defaults used."""
    svc = SiteConfigService()

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("core.site_config.AsyncSessionLocal", return_value=mock_ctx):
        params = await svc.get_effective_download_params("ehentai")

    assert params.retries == 5  # ehentai _sites.py default
    assert params.http_timeout == 45
    assert params.inactivity_timeout == 600


@pytest.mark.asyncio
async def test_get_effective_params_override_wins_over_default():
    """DB override takes precedence over _sites.py default."""
    svc = SiteConfigService()

    from db.models import SiteConfig

    mock_row = MagicMock(spec=SiteConfig)
    mock_row.overrides = {"download": {"retries": 10, "concurrency": 5}}
    mock_row.adaptive = {}

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_row
    mock_session.execute = AsyncMock(return_value=mock_result)

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("core.site_config.AsyncSessionLocal", return_value=mock_ctx):
        params = await svc.get_effective_download_params("ehentai")

    assert params.retries == 10  # override wins
    assert params.concurrency == 5  # override wins
    assert params.http_timeout == 45  # falls through to _sites.py default
    assert params.inactivity_timeout == 600  # falls through to _sites.py default


@pytest.mark.asyncio
async def test_get_effective_params_adaptive_fills_gaps():
    """Adaptive values fill gaps between override and _sites.py."""
    svc = SiteConfigService()

    from db.models import SiteConfig

    mock_row = MagicMock(spec=SiteConfig)
    mock_row.overrides = {"download": {"retries": 10}}
    mock_row.adaptive = {"download": {"sleep_request": 2.5}}

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_row
    mock_session.execute = AsyncMock(return_value=mock_result)

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("core.site_config.AsyncSessionLocal", return_value=mock_ctx):
        params = await svc.get_effective_download_params("ehentai")

    assert params.retries == 10  # override
    assert params.sleep_request == 2.5  # adaptive
    assert params.http_timeout == 45  # _sites.py default


# ── Cache behavior ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cache_returns_same_result_within_ttl():
    """Second call within TTL should not hit DB."""
    svc = SiteConfigService()

    from db.models import SiteConfig

    mock_row = MagicMock(spec=SiteConfig)
    mock_row.overrides = {}
    mock_row.adaptive = {}

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_row
    mock_session.execute = AsyncMock(return_value=mock_result)

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("core.site_config.AsyncSessionLocal", return_value=mock_ctx):
        await svc.get_effective_download_params("twitter")
        await svc.get_effective_download_params("twitter")

    # Should only have opened one session (one DB hit)
    assert mock_ctx.__aenter__.await_count == 1


# ── Concurrency validation ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_rejects_invalid_concurrency():
    """Concurrency must be 1-20."""
    svc = SiteConfigService()

    with pytest.raises(ValueError, match="concurrency must be 1-20"):
        await svc.update("ehentai", {"download": {"concurrency": 0}})

    with pytest.raises(ValueError, match="concurrency must be 1-20"):
        await svc.update("ehentai", {"download": {"concurrency": 25}})


# ── Batch load ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_all_download_params_returns_all_known_sources():
    """get_all_download_params covers all unique source_ids from GDL_SITES."""
    svc = SiteConfigService()

    mock_session = AsyncMock()
    # Return empty list for the batch query (must chain .scalars().all())
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = []
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars
    mock_session.execute = AsyncMock(return_value=mock_result)

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("core.site_config.AsyncSessionLocal", return_value=mock_ctx):
        result = await svc.get_all_download_params()

    assert "ehentai" in result
    assert "pixiv" in result
    assert "twitter" in result
    # Each value is a DownloadParams
    for params in result.values():
        assert isinstance(params, DownloadParams)


# ── Integration: update invalidates cache ────────────────────────────


@pytest.mark.asyncio
async def test_update_invalidates_cache():
    """After update(), cache is cleared and next read hits DB again."""
    svc = SiteConfigService()

    from db.models import SiteConfig

    call_count = 0

    def _make_mock_ctx(row):
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = row
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.get = AsyncMock(return_value=None)
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        return mock_ctx

    def _session_factory():
        nonlocal call_count
        call_count += 1
        if call_count <= 1:
            # First read: no overrides
            return _make_mock_ctx(None)
        else:
            # After update: has overrides
            row = MagicMock(spec=SiteConfig)
            row.overrides = {"download": {"retries": 8}}
            row.adaptive = {}
            return _make_mock_ctx(row)

    mock_redis = AsyncMock()
    mock_redis.publish = AsyncMock()

    with (
        patch("core.site_config.AsyncSessionLocal", side_effect=_session_factory),
        patch("core.site_config.get_redis", return_value=mock_redis),
    ):
        # First read — defaults
        p1 = await svc.get_effective_download_params("twitter")
        assert p1.retries == 4  # _sites.py default

        # Update triggers cache invalidation
        await svc.update("twitter", {"download": {"retries": 8}})

        # Next read should hit DB again (cache was invalidated)
        p2 = await svc.get_effective_download_params("twitter")
        assert p2.retries == 8


# ── Download pipeline fields ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_effective_params_provides_all_download_pipeline_fields():
    """Verify the service returns all fields the download pipeline needs."""
    svc = SiteConfigService()

    from db.models import SiteConfig

    mock_row = MagicMock(spec=SiteConfig)
    mock_row.overrides = {"download": {"concurrency": 4, "sleep_request": 1.5}}
    mock_row.adaptive = {}

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_row
    mock_session.execute = AsyncMock(return_value=mock_result)

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("core.site_config.AsyncSessionLocal", return_value=mock_ctx):
        params = await svc.get_effective_download_params("gallery_dl")

    # These are the exact fields download.py and source.py need
    assert params.concurrency == 4
    assert params.sleep_request == 1.5
    assert isinstance(params.retries, int)
    assert isinstance(params.http_timeout, int)
    assert isinstance(params.inactivity_timeout, int)
