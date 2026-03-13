"""
Tests for download rate limit control endpoints and Redis helper functions.

Covers:
- GET  /api/settings/rate-limits    — returns config for all sites
- PATCH /api/settings/rate-limits   — partial update of rate limit settings
- POST  /api/settings/rate-limits/override — set/clear full-speed override

And helper functions in core.redis_client:
- DownloadSemaphore.get_limit()
- get_download_delay()
- get_image_concurrency()
- is_rate_limit_boosted()

Uses the `client` fixture (pre-authenticated as admin).
Redis is mocked via the mock_redis fixture from conftest.
"""

from unittest.mock import AsyncMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures for non-admin client
# ---------------------------------------------------------------------------


@pytest.fixture
async def viewer_client(db_session, db_session_factory, mock_redis):
    """Authenticated client with viewer role (non-admin)."""
    import sys
    from httpx import ASGITransport, AsyncClient

    # conftest is registered in sys.modules as the session-level conftest
    _conftest = sys.modules.get("conftest") or sys.modules.get("tests.conftest")
    _app = _conftest._app
    _fake_get_db = _conftest._fake_get_db

    from core.auth import require_auth

    async def _override_get_db():
        yield db_session

    async def _override_require_auth():
        return {"user_id": 2, "role": "viewer"}

    _app.dependency_overrides[_fake_get_db] = _override_get_db
    _app.dependency_overrides[require_auth] = _override_require_auth

    _app.state.arq = AsyncMock()

    with (
        patch("core.redis_client.get_redis", return_value=mock_redis),
        patch("core.rate_limit.get_redis", return_value=mock_redis),
        patch("core.rate_limit.check_rate_limit", new_callable=AsyncMock),
        patch("routers.auth.get_redis", return_value=mock_redis),
        patch("routers.auth.check_rate_limit", new_callable=AsyncMock),
        patch("routers.auth.async_session", db_session_factory),
        patch("routers.settings.get_redis", return_value=mock_redis),
        patch("routers.settings.async_session", db_session_factory),
    ):
        transport = ASGITransport(app=_app, raise_app_exceptions=False)
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            cookies={"csrf_token": "test-csrf"},
            headers={"X-CSRF-Token": "test-csrf"},
        ) as ac:
            yield ac

    _app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /api/settings/rate-limits
# ---------------------------------------------------------------------------


class TestGetRateLimits:
    """GET /api/settings/rate-limits — returns current rate limit configuration."""

    async def test_get_rate_limits_returns_default_values_when_no_redis_keys(
        self, client, mock_redis
    ):
        """With no Redis keys set, should return config with fallback defaults."""
        mock_redis.get = AsyncMock(return_value=None)

        with patch("routers.settings.get_redis", return_value=mock_redis):
            resp = await client.get("/api/settings/rate-limits")

        assert resp.status_code == 200
        data = resp.json()

        assert "sites" in data
        assert "schedule" in data
        assert "override_active" in data
        assert "schedule_active" in data

        # Verify site keys exist
        assert "ehentai" in data["sites"]
        assert "pixiv" in data["sites"]
        assert "gallery_dl" in data["sites"]

        # Verify each site has expected fields
        for site in ("ehentai", "pixiv"):
            assert "concurrency" in data["sites"][site]
            assert "delay_ms" in data["sites"][site]
            assert "image_concurrency" in data["sites"][site]

        # Verify schedule has expected fields
        assert "enabled" in data["schedule"]
        assert "start_hour" in data["schedule"]
        assert "end_hour" in data["schedule"]
        assert "mode" in data["schedule"]

        # Default schedule settings
        assert data["schedule"]["enabled"] is False
        assert isinstance(data["schedule"]["start_hour"], int)
        assert isinstance(data["schedule"]["end_hour"], int)

        # Override and schedule should be inactive
        assert data["override_active"] is False
        assert data["schedule_active"] is False

    async def test_get_rate_limits_returns_configured_values_from_redis(
        self, client, mock_redis
    ):
        """With Redis keys set, should return their values rather than defaults."""

        def _get_side_effect(key):
            values = {
                "rate_limit:config:ehentai:concurrency": b"3",
                "rate_limit:config:ehentai:delay_ms": b"1500",
                "rate_limit:config:ehentai:image_concurrency": b"4",
                "rate_limit:config:pixiv:concurrency": b"1",
                "rate_limit:config:pixiv:page_delay_ms": b"2000",
                "rate_limit:config:pixiv:pagination_delay_ms": b"1500",
                "rate_limit:config:pixiv:illust_delay_ms": b"3000",
                "rate_limit:config:gallery_dl:concurrency": b"2",
                "rate_limit:config:gallery_dl:delay_ms": b"500",
                "rate_limit:schedule:enabled": b"1",
                "rate_limit:schedule:start_hour": b"2",
                "rate_limit:schedule:end_hour": b"8",
                "rate_limit:schedule:mode": b"full_speed",
                "rate_limit:override:unlocked": None,
                "rate_limit:schedule:active": None,
            }
            return values.get(key)

        mock_redis.get = AsyncMock(side_effect=_get_side_effect)

        with patch("routers.settings.get_redis", return_value=mock_redis):
            resp = await client.get("/api/settings/rate-limits")

        assert resp.status_code == 200
        data = resp.json()

        assert data["sites"]["ehentai"]["concurrency"] == 3
        assert data["sites"]["ehentai"]["delay_ms"] == 1500
        assert data["sites"]["ehentai"]["image_concurrency"] == 4
        assert data["sites"]["pixiv"]["concurrency"] == 1
        # pixiv uses page_delay_ms, not delay_ms (delay_ms is None for pixiv)
        assert data["sites"]["pixiv"]["page_delay_ms"] == 2000
        assert data["sites"]["gallery_dl"]["concurrency"] == 2
        assert data["schedule"]["enabled"] is True
        assert data["schedule"]["start_hour"] == 2
        assert data["schedule"]["end_hour"] == 8
        assert data["schedule"]["mode"] == "full_speed"

    async def test_get_rate_limits_shows_override_active_when_key_exists(
        self, client, mock_redis
    ):
        """When override:unlocked key exists in Redis, override_active should be True."""

        def _get_side_effect(key):
            if key == "rate_limit:override:unlocked":
                return b"1"
            return None

        mock_redis.get = AsyncMock(side_effect=_get_side_effect)

        with patch("routers.settings.get_redis", return_value=mock_redis):
            resp = await client.get("/api/settings/rate-limits")

        assert resp.status_code == 200
        assert resp.json()["override_active"] is True

    async def test_get_rate_limits_shows_schedule_active_when_key_set(
        self, client, mock_redis
    ):
        """When schedule:active=1 in Redis, schedule_active should be True."""

        def _get_side_effect(key):
            if key == "rate_limit:schedule:active":
                return b"1"
            return None

        mock_redis.get = AsyncMock(side_effect=_get_side_effect)

        with patch("routers.settings.get_redis", return_value=mock_redis):
            resp = await client.get("/api/settings/rate-limits")

        assert resp.status_code == 200
        assert resp.json()["schedule_active"] is True

    async def test_get_rate_limits_requires_admin_unauthenticated_returns_401(
        self, unauthed_client
    ):
        """Unauthenticated request should return 401."""
        resp = await unauthed_client.get("/api/settings/rate-limits")
        assert resp.status_code == 401

    async def test_get_rate_limits_requires_admin_viewer_returns_403(
        self, viewer_client
    ):
        """Viewer-role request should return 403."""
        with patch("routers.settings.get_redis", return_value=AsyncMock(get=AsyncMock(return_value=None))):
            resp = await viewer_client.get("/api/settings/rate-limits")
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# PATCH /api/settings/rate-limits
# ---------------------------------------------------------------------------


class TestPatchRateLimits:
    """PATCH /api/settings/rate-limits — partial update of rate limit settings."""

    async def test_patch_rate_limits_updates_site_concurrency(
        self, client, mock_redis
    ):
        """Patching concurrency for a site should write to Redis and return ok."""
        mock_redis.set = AsyncMock(return_value=True)

        payload = {"sites": {"ehentai": {"concurrency": 3}}}
        with patch("routers.settings.get_redis", return_value=mock_redis):
            resp = await client.patch("/api/settings/rate-limits", json=payload)

        assert resp.status_code == 200
        data = resp.json()
        assert "sites" in data
        assert "schedule" in data
        mock_redis.set.assert_any_await(
            "rate_limit:config:ehentai:concurrency", "3"
        )

    async def test_patch_rate_limits_updates_site_delay_ms(
        self, client, mock_redis
    ):
        """Patching delay_ms for a site should write to Redis and return ok."""
        mock_redis.set = AsyncMock(return_value=True)

        payload = {"sites": {"pixiv": {"delay_ms": 2000}}}
        with patch("routers.settings.get_redis", return_value=mock_redis):
            resp = await client.patch("/api/settings/rate-limits", json=payload)

        assert resp.status_code == 200
        mock_redis.set.assert_any_await(
            "rate_limit:config:pixiv:delay_ms", "2000"
        )

    async def test_patch_rate_limits_updates_image_concurrency(
        self, client, mock_redis
    ):
        """Patching image_concurrency for a site should write to Redis and return ok."""
        mock_redis.set = AsyncMock(return_value=True)

        payload = {"sites": {"pixiv": {"image_concurrency": 4}}}
        with patch("routers.settings.get_redis", return_value=mock_redis):
            resp = await client.patch("/api/settings/rate-limits", json=payload)

        assert resp.status_code == 200
        mock_redis.set.assert_any_await(
            "rate_limit:config:pixiv:image_concurrency", "4"
        )

    async def test_patch_rate_limits_updates_schedule_settings(
        self, client, mock_redis
    ):
        """Patching schedule fields should write all provided schedule keys to Redis."""
        mock_redis.set = AsyncMock(return_value=True)

        payload = {
            "schedule": {
                "enabled": True,
                "start_hour": 1,
                "end_hour": 7,
                "mode": "full_speed",
            }
        }
        with patch("routers.settings.get_redis", return_value=mock_redis):
            resp = await client.patch("/api/settings/rate-limits", json=payload)

        assert resp.status_code == 200
        data = resp.json()
        assert "sites" in data
        mock_redis.set.assert_any_await("rate_limit:schedule:enabled", "1")
        mock_redis.set.assert_any_await("rate_limit:schedule:start_hour", "1")
        mock_redis.set.assert_any_await("rate_limit:schedule:end_hour", "7")
        mock_redis.set.assert_any_await("rate_limit:schedule:mode", "full_speed")

    async def test_patch_rate_limits_rejects_concurrency_zero(
        self, client, mock_redis
    ):
        """Concurrency value of 0 should return 400 (out of range 1-10)."""
        payload = {"sites": {"ehentai": {"concurrency": 0}}}
        with patch("routers.settings.get_redis", return_value=mock_redis):
            resp = await client.patch("/api/settings/rate-limits", json=payload)

        assert resp.status_code == 400

    async def test_patch_rate_limits_rejects_concurrency_above_max(
        self, client, mock_redis
    ):
        """Concurrency value of 11 should return 400 (out of range 1-10)."""
        payload = {"sites": {"ehentai": {"concurrency": 11}}}
        with patch("routers.settings.get_redis", return_value=mock_redis):
            resp = await client.patch("/api/settings/rate-limits", json=payload)

        assert resp.status_code == 400

    async def test_patch_rate_limits_rejects_negative_delay_ms(
        self, client, mock_redis
    ):
        """Negative delay_ms should return 400."""
        payload = {"sites": {"ehentai": {"delay_ms": -1}}}
        with patch("routers.settings.get_redis", return_value=mock_redis):
            resp = await client.patch("/api/settings/rate-limits", json=payload)

        assert resp.status_code == 400

    async def test_patch_rate_limits_rejects_delay_ms_above_max(
        self, client, mock_redis
    ):
        """delay_ms of 10001 should return 400 (out of range 0-10000)."""
        payload = {"sites": {"ehentai": {"delay_ms": 10001}}}
        with patch("routers.settings.get_redis", return_value=mock_redis):
            resp = await client.patch("/api/settings/rate-limits", json=payload)

        assert resp.status_code == 400

    async def test_patch_rate_limits_accepts_boundary_delay_ms_10000(
        self, client, mock_redis
    ):
        """delay_ms of exactly 10000 should be accepted as valid."""
        mock_redis.set = AsyncMock(return_value=True)
        payload = {"sites": {"ehentai": {"delay_ms": 10000}}}
        with patch("routers.settings.get_redis", return_value=mock_redis):
            resp = await client.patch("/api/settings/rate-limits", json=payload)

        assert resp.status_code == 200

    async def test_patch_rate_limits_rejects_schedule_hour_above_23(
        self, client, mock_redis
    ):
        """schedule.start_hour of 24 should return 400 (out of range 0-23)."""
        payload = {"schedule": {"start_hour": 24}}
        with patch("routers.settings.get_redis", return_value=mock_redis):
            resp = await client.patch("/api/settings/rate-limits", json=payload)

        assert resp.status_code == 400

    async def test_patch_rate_limits_rejects_schedule_end_hour_negative(
        self, client, mock_redis
    ):
        """schedule.end_hour of -1 should return 400."""
        payload = {"schedule": {"end_hour": -1}}
        with patch("routers.settings.get_redis", return_value=mock_redis):
            resp = await client.patch("/api/settings/rate-limits", json=payload)

        assert resp.status_code == 400

    async def test_patch_rate_limits_accepts_boundary_hours_0_and_23(
        self, client, mock_redis
    ):
        """Boundary values 0 and 23 for schedule hours should be accepted."""
        mock_redis.set = AsyncMock(return_value=True)
        payload = {"schedule": {"start_hour": 0, "end_hour": 23}}
        with patch("routers.settings.get_redis", return_value=mock_redis):
            resp = await client.patch("/api/settings/rate-limits", json=payload)

        assert resp.status_code == 200

    async def test_patch_rate_limits_partial_update_only_sets_provided_fields(
        self, client, mock_redis
    ):
        """Only provided fields should be written to Redis; omitted fields left untouched."""
        mock_redis.set = AsyncMock(return_value=True)

        # Only update concurrency, not delay_ms or image_concurrency
        payload = {"sites": {"ehentai": {"concurrency": 4}}}
        with patch("routers.settings.get_redis", return_value=mock_redis):
            resp = await client.patch("/api/settings/rate-limits", json=payload)

        assert resp.status_code == 200

        # Verify set was called for concurrency but NOT for delay_ms or image_concurrency
        called_keys = [call.args[0] for call in mock_redis.set.call_args_list]
        assert "rate_limit:config:ehentai:concurrency" in called_keys
        assert "rate_limit:config:ehentai:delay_ms" not in called_keys
        assert "rate_limit:config:ehentai:image_concurrency" not in called_keys

    async def test_patch_rate_limits_empty_body_is_noop(
        self, client, mock_redis
    ):
        """Empty body (no sites, no schedule) should succeed without touching Redis."""
        mock_redis.set = AsyncMock(return_value=True)

        with patch("routers.settings.get_redis", return_value=mock_redis):
            resp = await client.patch("/api/settings/rate-limits", json={})

        assert resp.status_code == 200
        data = resp.json()
        assert "sites" in data
        assert "schedule" in data

    async def test_patch_rate_limits_rejects_invalid_schedule_mode(
        self, client, mock_redis
    ):
        """Invalid schedule mode string should return 400."""
        payload = {"schedule": {"mode": "turbo_boost"}}
        with patch("routers.settings.get_redis", return_value=mock_redis):
            resp = await client.patch("/api/settings/rate-limits", json=payload)

        assert resp.status_code == 400

    async def test_patch_rate_limits_accepts_standard_schedule_mode(
        self, client, mock_redis
    ):
        """schedule.mode 'standard' should be accepted."""
        mock_redis.set = AsyncMock(return_value=True)
        payload = {"schedule": {"mode": "standard"}}
        with patch("routers.settings.get_redis", return_value=mock_redis):
            resp = await client.patch("/api/settings/rate-limits", json=payload)

        assert resp.status_code == 200

    async def test_patch_rate_limits_requires_admin_unauthenticated_returns_401(
        self, unauthed_client
    ):
        """Unauthenticated request should return 401."""
        resp = await unauthed_client.patch(
            "/api/settings/rate-limits",
            json={"sites": {"ehentai": {"concurrency": 2}}},
        )
        assert resp.status_code == 401

    async def test_patch_rate_limits_requires_admin_viewer_returns_403(
        self, viewer_client
    ):
        """Viewer-role request should return 403."""
        with patch("routers.settings.get_redis", return_value=AsyncMock(set=AsyncMock())):
            resp = await viewer_client.patch(
                "/api/settings/rate-limits",
                json={"sites": {"ehentai": {"concurrency": 2}}},
            )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST /api/settings/rate-limits/override
# ---------------------------------------------------------------------------


class TestSetRateLimitOverride:
    """POST /api/settings/rate-limits/override — set or clear full-speed override."""

    async def test_set_override_unlocked_true_sets_redis_key(
        self, client, mock_redis
    ):
        """Setting unlocked=true should write override:unlocked to Redis."""
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.delete = AsyncMock(return_value=1)

        with patch("routers.settings.get_redis", return_value=mock_redis):
            resp = await client.post(
                "/api/settings/rate-limits/override", json={"unlocked": True}
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["override_active"] is True
        mock_redis.set.assert_awaited_once_with("rate_limit:override:unlocked", "1")

    async def test_set_override_unlocked_false_deletes_redis_key(
        self, client, mock_redis
    ):
        """Setting unlocked=false should delete override:unlocked from Redis."""
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.delete = AsyncMock(return_value=1)

        with patch("routers.settings.get_redis", return_value=mock_redis):
            resp = await client.post(
                "/api/settings/rate-limits/override", json={"unlocked": False}
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["override_active"] is False
        mock_redis.delete.assert_awaited_once_with("rate_limit:override:unlocked")

    async def test_set_override_requires_admin_unauthenticated_returns_401(
        self, unauthed_client
    ):
        """Unauthenticated request should return 401."""
        resp = await unauthed_client.post(
            "/api/settings/rate-limits/override", json={"unlocked": True}
        )
        assert resp.status_code == 401

    async def test_set_override_requires_admin_viewer_returns_403(
        self, viewer_client
    ):
        """Viewer-role request should return 403."""
        with patch("routers.settings.get_redis", return_value=AsyncMock(set=AsyncMock(), delete=AsyncMock())):
            resp = await viewer_client.post(
                "/api/settings/rate-limits/override", json={"unlocked": True}
            )
        assert resp.status_code == 403

    async def test_set_override_missing_field_returns_422(self, client):
        """Request without required 'unlocked' field should return 422."""
        resp = await client.post("/api/settings/rate-limits/override", json={})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Helper: is_rate_limit_boosted()
# ---------------------------------------------------------------------------


class TestIsRateLimitBoosted:
    """Unit tests for core.redis_client.is_rate_limit_boosted()."""

    async def test_is_rate_limit_boosted_false_by_default(self):
        """Returns False when no override or schedule keys are set."""
        from core.redis_client import is_rate_limit_boosted

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        with patch("core.redis_client.get_redis", return_value=mock_redis):
            result = await is_rate_limit_boosted()

        assert result is False

    async def test_is_rate_limit_boosted_true_when_override_exists(self):
        """Returns True when rate_limit:override:unlocked key exists in Redis."""
        from core.redis_client import is_rate_limit_boosted

        mock_redis = AsyncMock()

        def _get(key):
            if key == "rate_limit:override:unlocked":
                return b"1"
            return None

        mock_redis.get = AsyncMock(side_effect=_get)

        with patch("core.redis_client.get_redis", return_value=mock_redis):
            result = await is_rate_limit_boosted()

        assert result is True

    async def test_is_rate_limit_boosted_true_when_schedule_active_full_speed(self):
        """Returns True when schedule:active=1 and schedule:mode=full_speed."""
        from core.redis_client import is_rate_limit_boosted

        mock_redis = AsyncMock()

        def _get(key):
            values = {
                "rate_limit:override:unlocked": None,
                "rate_limit:schedule:active": b"1",
                "rate_limit:schedule:mode": b"full_speed",
            }
            return values.get(key)

        mock_redis.get = AsyncMock(side_effect=_get)

        with patch("core.redis_client.get_redis", return_value=mock_redis):
            result = await is_rate_limit_boosted()

        assert result is True

    async def test_is_rate_limit_boosted_false_when_schedule_active_standard_mode(self):
        """Returns False when schedule:active=1 but mode is 'standard'."""
        from core.redis_client import is_rate_limit_boosted

        mock_redis = AsyncMock()

        def _get(key):
            values = {
                "rate_limit:override:unlocked": None,
                "rate_limit:schedule:active": b"1",
                "rate_limit:schedule:mode": b"standard",
            }
            return values.get(key)

        mock_redis.get = AsyncMock(side_effect=_get)

        with patch("core.redis_client.get_redis", return_value=mock_redis):
            result = await is_rate_limit_boosted()

        assert result is False

    async def test_is_rate_limit_boosted_true_when_schedule_active_mode_not_set(self):
        """Returns True when schedule:active=1 but schedule:mode key doesn't exist (defaults to full_speed)."""
        from core.redis_client import is_rate_limit_boosted

        mock_redis = AsyncMock()

        def _get(key):
            values = {
                "rate_limit:override:unlocked": None,
                "rate_limit:schedule:active": b"1",
                "rate_limit:schedule:mode": None,
            }
            return values.get(key)

        mock_redis.get = AsyncMock(side_effect=_get)

        with patch("core.redis_client.get_redis", return_value=mock_redis):
            result = await is_rate_limit_boosted()

        assert result is True

    async def test_is_rate_limit_boosted_false_when_schedule_mode_full_speed_but_inactive(self):
        """Returns False when mode=full_speed but schedule:active is not set."""
        from core.redis_client import is_rate_limit_boosted

        mock_redis = AsyncMock()

        def _get(key):
            values = {
                "rate_limit:override:unlocked": None,
                "rate_limit:schedule:active": None,
                "rate_limit:schedule:mode": b"full_speed",
            }
            return values.get(key)

        mock_redis.get = AsyncMock(side_effect=_get)

        with patch("core.redis_client.get_redis", return_value=mock_redis):
            result = await is_rate_limit_boosted()

        assert result is False


# ---------------------------------------------------------------------------
# Helper: get_download_delay()
# ---------------------------------------------------------------------------


class TestGetDownloadDelay:
    """Unit tests for core.redis_client.get_download_delay()."""

    async def test_get_download_delay_returns_default_when_no_redis_key(self):
        """Returns default_ms converted to seconds when no Redis key is set."""
        from core.redis_client import get_download_delay

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        with patch("core.redis_client.get_redis", return_value=mock_redis):
            result = await get_download_delay("ehentai", default_ms=500)

        assert result == pytest.approx(0.5)

    async def test_get_download_delay_returns_configured_value_from_redis(self):
        """Returns Redis value (ms) divided by 1000 as seconds."""
        from core.redis_client import get_download_delay

        mock_redis = AsyncMock()

        def _get(key):
            if key == "rate_limit:config:ehentai:delay_ms":
                return b"2000"
            return None

        mock_redis.get = AsyncMock(side_effect=_get)

        with patch("core.redis_client.get_redis", return_value=mock_redis):
            result = await get_download_delay("ehentai", default_ms=0)

        assert result == pytest.approx(2.0)

    async def test_get_download_delay_returns_zero_when_override_active(self):
        """Returns 0.0 when override boost mode is active (rate limiting bypassed)."""
        from core.redis_client import get_download_delay

        mock_redis = AsyncMock()

        def _get(key):
            if key == "rate_limit:override:unlocked":
                return b"1"
            if key == "rate_limit:config:ehentai:delay_ms":
                return b"3000"
            return None

        mock_redis.get = AsyncMock(side_effect=_get)

        with patch("core.redis_client.get_redis", return_value=mock_redis):
            result = await get_download_delay("ehentai", default_ms=1000)

        assert result == 0.0

    async def test_get_download_delay_returns_zero_when_schedule_boost_active(self):
        """Returns 0.0 when schedule-based boost mode is active."""
        from core.redis_client import get_download_delay

        mock_redis = AsyncMock()

        def _get(key):
            values = {
                "rate_limit:override:unlocked": None,
                "rate_limit:schedule:active": b"1",
                "rate_limit:schedule:mode": b"full_speed",
                "rate_limit:config:pixiv:delay_ms": b"500",
            }
            return values.get(key)

        mock_redis.get = AsyncMock(side_effect=_get)

        with patch("core.redis_client.get_redis", return_value=mock_redis):
            result = await get_download_delay("pixiv", default_ms=500)

        assert result == 0.0

    async def test_get_download_delay_default_ms_zero_returns_zero(self):
        """Returns 0.0 seconds when default_ms=0 and no Redis key exists."""
        from core.redis_client import get_download_delay

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        with patch("core.redis_client.get_redis", return_value=mock_redis):
            result = await get_download_delay("gallery_dl", default_ms=0)

        assert result == 0.0


# ---------------------------------------------------------------------------
# Helper: get_image_concurrency()
# ---------------------------------------------------------------------------


class TestGetImageConcurrency:
    """Unit tests for core.redis_client.get_image_concurrency()."""

    async def test_get_image_concurrency_returns_default_when_no_redis_key(self):
        """Returns the provided default when no Redis key is set."""
        from core.redis_client import get_image_concurrency

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        with patch("core.redis_client.get_redis", return_value=mock_redis):
            result = await get_image_concurrency("ehentai", default=3)

        assert result == 3

    async def test_get_image_concurrency_returns_configured_value_from_redis(self):
        """Returns the integer value stored in Redis for the source."""
        from core.redis_client import get_image_concurrency

        mock_redis = AsyncMock()

        def _get(key):
            if key == "rate_limit:config:pixiv:image_concurrency":
                return b"6"
            return None

        mock_redis.get = AsyncMock(side_effect=_get)

        with patch("core.redis_client.get_redis", return_value=mock_redis):
            result = await get_image_concurrency("pixiv", default=1)

        assert result == 6

    async def test_get_image_concurrency_falls_back_to_default_on_invalid_redis_value(self):
        """Returns default when Redis value is not a valid integer."""
        from core.redis_client import get_image_concurrency

        mock_redis = AsyncMock()

        def _get(key):
            if key == "rate_limit:config:ehentai:image_concurrency":
                return b"not_a_number"
            return None

        mock_redis.get = AsyncMock(side_effect=_get)

        with patch("core.redis_client.get_redis", return_value=mock_redis):
            result = await get_image_concurrency("ehentai", default=2)

        assert result == 2


# ---------------------------------------------------------------------------
# Helper: DownloadSemaphore.get_limit()
# ---------------------------------------------------------------------------


class TestDownloadSemaphoreGetLimit:
    """Unit tests for DownloadSemaphore.get_limit() class method."""

    async def test_get_limit_returns_default_from_limits_dict_when_no_redis_key(self):
        """Returns hardcoded _LIMITS value for known source when no Redis key is set."""
        from core.redis_client import DownloadSemaphore

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        with patch("core.redis_client.get_redis", return_value=mock_redis):
            result = await DownloadSemaphore.get_limit("ehentai")

        # ehentai has default 2 in _LIMITS
        assert result == DownloadSemaphore._LIMITS["ehentai"]

    async def test_get_limit_returns_configured_value_from_redis(self):
        """Returns the integer value stored in Redis for the source."""
        from core.redis_client import DownloadSemaphore

        mock_redis = AsyncMock()

        def _get(key):
            if key == "rate_limit:config:ehentai:concurrency":
                return b"5"
            return None

        mock_redis.get = AsyncMock(side_effect=_get)

        with patch("core.redis_client.get_redis", return_value=mock_redis):
            result = await DownloadSemaphore.get_limit("ehentai")

        assert result == 5

    async def test_get_limit_falls_back_to_provided_default_for_unknown_source(self):
        """For unknown source with no Redis key, falls back to provided default arg."""
        from core.redis_client import DownloadSemaphore

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        with patch("core.redis_client.get_redis", return_value=mock_redis):
            result = await DownloadSemaphore.get_limit("unknown_site", default=7)

        assert result == 7

    async def test_get_limit_falls_back_to_default_on_invalid_redis_value(self):
        """Returns _LIMITS fallback when Redis value is not a valid integer."""
        from core.redis_client import DownloadSemaphore

        mock_redis = AsyncMock()

        def _get(key):
            if key == "rate_limit:config:pixiv:concurrency":
                return b"invalid"
            return None

        mock_redis.get = AsyncMock(side_effect=_get)

        with patch("core.redis_client.get_redis", return_value=mock_redis):
            result = await DownloadSemaphore.get_limit("pixiv")

        # Falls back to _LIMITS["pixiv"] = 2
        assert result == DownloadSemaphore._LIMITS["pixiv"]

    async def test_get_limit_reads_correct_redis_key_pattern(self):
        """Verifies that get_limit reads from rate_limit:config:{source}:concurrency key."""
        from core.redis_client import DownloadSemaphore

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        with patch("core.redis_client.get_redis", return_value=mock_redis):
            await DownloadSemaphore.get_limit("gallery_dl")

        mock_redis.get.assert_awaited_with("rate_limit:config:gallery_dl:concurrency")
