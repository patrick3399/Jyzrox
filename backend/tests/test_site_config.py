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


# ── Proxy URL validation ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_site_config_rejects_socks5_proxy_url_without_socks_support():
    """A socks5:// proxy must be refused at write time.

    gallery-dl is the only consumer of proxy_url and its isolated venv ships
    without PySocks, so an accepted SOCKS proxy fails every download for the
    site with "Missing dependencies for SOCKS support".
    """
    svc = SiteConfigService()

    with pytest.raises(ValueError, match="SOCKS proxies are not supported"):
        await svc.update("ehentai", {"download": {"proxy_url": "socks5://127.0.0.1:1080"}})


@pytest.mark.parametrize("proxy_url", ["http://proxy.local:8080", "https://proxy.local:8443", None])
def test_site_config_accepts_http_and_https_proxy_url(proxy_url):
    """Rejecting SOCKS must not take the supported schemes (or a null reset) with it."""
    SiteConfigService._validate_overrides({"download": {"proxy_url": proxy_url}})


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
        mock_session.expunge = MagicMock()
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


@pytest.mark.asyncio
async def test_reset_adaptive_resets_redis_before_committing_db():
    """Regression for edge case #138: reset_adaptive() must reset the Redis
    adaptive state BEFORE committing the DB clear. The old order (commit then
    Redis reset) left stale Redis adaptive state if the process died between the
    two — surviving across restart with an already-cleared DB row.
    """
    from db.models import SiteConfig

    svc = SiteConfigService()

    mock_row = MagicMock(spec=SiteConfig)
    mock_row.adaptive = {"backoff": 3}

    order: list[str] = []

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=mock_row)
    mock_session.commit = AsyncMock(side_effect=lambda: order.append("commit"))
    mock_session.expunge = MagicMock()

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    async def _reset(source_id):
        order.append("reset")

    with (
        patch("core.site_config.AsyncSessionLocal", return_value=mock_ctx),
        patch("core.adaptive.adaptive_engine.reset", side_effect=_reset),
        patch.object(svc, "_invalidate", new_callable=AsyncMock),
        patch.object(svc, "_merge", return_value=DownloadParams()),
    ):
        await svc.reset_adaptive("ehentai")

    assert order == ["reset", "commit"], f"Redis reset must precede DB commit, got {order}"


def test_spread_personas_defaults_off_and_override_turns_it_on():
    from db.models import SiteConfig

    svc = SiteConfigService()
    assert svc._merge("twitter", None).spread_personas is False
    row = SiteConfig(source_id="twitter", overrides={"download": {"spread_personas": True}}, adaptive={})
    assert svc._merge("twitter", row).spread_personas is True


def test_spread_personas_override_must_be_boolean():
    with pytest.raises(ValueError, match="spread_personas"):
        SiteConfigService._validate_overrides({"download": {"spread_personas": "yes"}})


# ── Sleep validation (sleep_request / sleep_download) ────────────────


def _mock_session_ctx(row):
    """AsyncSessionLocal() replacement whose session.get() returns `row`."""
    session = AsyncMock()
    session.get = AsyncMock(return_value=row)
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.expunge = MagicMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx, session


def test_validate_sleep_accepts_zero_as_explicit_off():
    """0 means 'no sleep' (distinct from null = gallery-dl default); it used to be rejected as <= 0."""
    for field in ("sleep_request", "sleep_download"):
        SiteConfigService._validate_overrides({"download": {field: 0}})
        SiteConfigService._validate_overrides({"download": {field: 0.0}})
        SiteConfigService._validate_overrides({"download": {field: [0, 0]}})
        SiteConfigService._validate_overrides({"download": {field: [0, 2.5]}})
        SiteConfigService._validate_overrides({"download": {field: None}})


@pytest.mark.parametrize("field", ["sleep_request", "sleep_download"])
@pytest.mark.parametrize("value", [-1, 3601, [3, 1], [-1, 2], [1, 3601], [1, 2, 3], [1], "2", True, [1, "2"]])
def test_validate_sleep_rejects_out_of_range_or_malformed_values(field, value):
    with pytest.raises(ValueError, match=field):
        SiteConfigService._validate_overrides({"download": {field: value}})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "download",
    [
        {"sleep_download": 300},
        {"sleep_download": [1, 400]},
        {"sleep_request": [10, 300]},
        {"sleep_request": 301},
    ],
)
async def test_update_rejects_sleep_longer_than_inactivity_timeout(download):
    """A single sleep >= the watchdog window would be killed as idle (instagram default window: 300s)."""
    svc = SiteConfigService()
    ctx, session = _mock_session_ctx(None)

    with (
        patch("core.site_config.AsyncSessionLocal", return_value=ctx),
        pytest.raises(ValueError, match="inactivity_timeout"),
    ):
        await svc.update("instagram", {"download": download})

    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_rejects_inactivity_timeout_shorter_than_stored_sleep():
    """Lowering the window below an already-stored sleep is the same hazard, checked on the merged result."""
    from db.models import SiteConfig

    svc = SiteConfigService()
    row = SiteConfig(source_id="twitter", overrides={"download": {"sleep_download": 100}}, adaptive={})
    ctx, session = _mock_session_ctx(row)

    with (
        patch("core.site_config.AsyncSessionLocal", return_value=ctx),
        pytest.raises(ValueError, match="inactivity_timeout"),
    ):
        await svc.update("twitter", {"download": {"inactivity_timeout": 60}})

    session.commit.assert_not_awaited()
    assert row.overrides == {"download": {"sleep_download": 100}}


@pytest.mark.asyncio
async def test_update_accepts_sleep_below_inactivity_timeout_and_persists_it():
    svc = SiteConfigService()
    ctx, session = _mock_session_ctx(None)

    with (
        patch("core.site_config.AsyncSessionLocal", return_value=ctx),
        patch("core.site_config.get_redis", return_value=AsyncMock()),
    ):
        params, row = await svc.update("twitter", {"download": {"sleep_download": [1, 3]}})

    assert params.sleep_download == (1, 3)
    assert row.overrides == {"download": {"sleep_download": [1, 3]}}
    session.commit.assert_awaited_once()


def test_merge_normalises_stored_sleep_lists_to_tuples():
    from db.models import SiteConfig

    row = SiteConfig(
        source_id="twitter",
        overrides={"download": {"sleep_request": [1.0, 2.0], "sleep_download": [3.0, 4.0]}},
        adaptive={},
    )
    params = SiteConfigService()._merge("twitter", row)
    assert params.sleep_request == (1.0, 2.0)
    assert params.sleep_download == (3.0, 4.0)


# ── Reset / defaults / extractor defaults ────────────────────────────


@pytest.mark.asyncio
async def test_reset_section_path_clears_all_download_overrides():
    """field_path='download' (one segment) drops the whole section and leaves other sections alone."""
    from db.models import SiteConfig

    svc = SiteConfigService()
    row = SiteConfig(
        source_id="twitter",
        overrides={"download": {"retries": 8, "sleep_download": 2}, "field_mapping": {"title": "t"}},
        adaptive={},
    )
    ctx, session = _mock_session_ctx(row)

    with (
        patch("core.site_config.AsyncSessionLocal", return_value=ctx),
        patch.object(svc, "_invalidate", new_callable=AsyncMock),
    ):
        params, _ = await svc.reset("twitter", "download")

    assert row.overrides == {"field_mapping": {"title": "t"}}
    assert params.retries == 4  # _sites.py default
    assert params.sleep_download is None
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("field_path", ["", "bogus", "download.retries.extra", "a.b.c.d"])
async def test_reset_rejects_unknown_or_overlong_field_path(field_path):
    svc = SiteConfigService()
    with pytest.raises(ValueError, match="field_path"):
        await svc.reset("twitter", field_path)


def test_defaults_ignore_overrides_and_adaptive():
    """defaults() is the Jyzrox layer only: what a reset would fall back to."""
    svc = SiteConfigService()
    assert svc.defaults("ehentai") == svc._merge("ehentai", None)
    assert svc.defaults("ehentai").retries == 5


def test_extractor_defaults_instagram_request_interval():
    """IG's extractor class declares request_interval = (6.0, 12.0); surfaced as an informational hint."""
    pytest.importorskip("gallery_dl")
    assert SiteConfigService().extractor_defaults("instagram") == {
        "sleep_request": [6.0, 12.0],
        "sleep_download": None,
    }


def test_extractor_defaults_unknown_source_returns_nulls():
    assert SiteConfigService().extractor_defaults("no-such-site-xyz") == {
        "sleep_request": None,
        "sleep_download": None,
    }


def test_extractor_defaults_lookup_failure_returns_nulls():
    from core import site_config

    site_config._extractor_defaults_for.cache_clear()
    try:
        with patch("core.site_config.gdl_extractor_name", side_effect=RuntimeError("boom")):
            assert SiteConfigService().extractor_defaults("instagram") == {
                "sleep_request": None,
                "sleep_download": None,
            }
    finally:
        site_config._extractor_defaults_for.cache_clear()
