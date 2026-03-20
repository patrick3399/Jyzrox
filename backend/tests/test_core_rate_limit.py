"""Tests for core.rate_limit — trusted networks, IP extraction, rate limiting, middleware.

Covers:
- _trusted_networks(): CIDR parsing, comma-separated, invalid entries, LRU cache
- _is_trusted(): IP in/out of network, invalid IP, IPv6
- check_rate_limit(): disabled noop, first request expiry, under/over limit, 429
- get_client_ip(): no header, trusted proxy forwarding, multiple IPs, no client
- _is_private(): 10.x, 172.16.x, 192.168.x, public IP
- RateLimitMiddleware.dispatch(): health bypass, private IP bypass, 429 response
"""

import ipaddress
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import core.rate_limit as mod

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(**kwargs):
    """Build a minimal mock settings object for rate_limit module."""
    defaults = dict(
        trusted_proxies="",
        rate_limit_enabled=True,
        rate_limit_login=5,
        rate_limit_window=300,
    )
    defaults.update(kwargs)
    m = MagicMock()
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


def _make_request(host="1.2.3.4", headers=None, path="/api/some", method="GET"):
    """Build a minimal mock Request object."""
    req = MagicMock()
    req.client = MagicMock()
    req.client.host = host
    req.headers = headers if headers is not None else {}
    req.url = MagicMock()
    req.url.path = path
    req.method = method
    return req


# ---------------------------------------------------------------------------
# TestTrustedNetworks
# ---------------------------------------------------------------------------


class TestTrustedNetworks:
    def setup_method(self):
        mod._trusted_networks.cache_clear()

    def teardown_method(self):
        mod._trusted_networks.cache_clear()

    def test_single_cidr_parsed_correctly(self):
        with patch("core.rate_limit.settings", _make_settings(trusted_proxies="172.16.0.0/12")):
            nets = mod._trusted_networks()
        assert len(nets) == 1
        assert isinstance(nets[0], ipaddress.IPv4Network | ipaddress.IPv6Network)
        assert ipaddress.ip_address("172.20.0.1") in nets[0]

    def test_comma_separated_multiple_cidrs(self):
        with patch("core.rate_limit.settings", _make_settings(trusted_proxies="10.0.0.0/8,172.16.0.0/12")):
            nets = mod._trusted_networks()
        assert len(nets) == 2

    def test_invalid_entry_is_skipped_with_warning(self, caplog):
        import logging

        with patch("core.rate_limit.settings", _make_settings(trusted_proxies="10.0.0.0/8,NOT_VALID")):
            with caplog.at_level(logging.WARNING):
                nets = mod._trusted_networks()
        assert len(nets) == 1
        assert any("NOT_VALID" in r.message for r in caplog.records)

    def test_empty_string_returns_empty_list(self):
        with patch("core.rate_limit.settings", _make_settings(trusted_proxies="")):
            nets = mod._trusted_networks()
        assert nets == []

    def test_result_is_cached_across_calls(self):
        with patch("core.rate_limit.settings", _make_settings(trusted_proxies="127.0.0.1/32")):
            first = mod._trusted_networks()
            second = mod._trusted_networks()
        assert first is second


# ---------------------------------------------------------------------------
# TestIsTrusted
# ---------------------------------------------------------------------------


class TestIsTrusted:
    def setup_method(self):
        mod._trusted_networks.cache_clear()

    def teardown_method(self):
        mod._trusted_networks.cache_clear()

    def test_ip_inside_trusted_network_returns_true(self):
        with patch("core.rate_limit.settings", _make_settings(trusted_proxies="10.0.0.0/8")):
            result = mod._is_trusted("10.5.5.5")
        assert result is True

    def test_ip_outside_trusted_network_returns_false(self):
        with patch("core.rate_limit.settings", _make_settings(trusted_proxies="10.0.0.0/8")):
            result = mod._is_trusted("8.8.8.8")
        assert result is False

    def test_invalid_ip_string_returns_false(self):
        with patch("core.rate_limit.settings", _make_settings(trusted_proxies="10.0.0.0/8")):
            result = mod._is_trusted("not_an_ip")
        assert result is False

    def test_ipv6_address_in_trusted_range_returns_true(self):
        with patch("core.rate_limit.settings", _make_settings(trusted_proxies="::1/128")):
            result = mod._is_trusted("::1")
        assert result is True


# ---------------------------------------------------------------------------
# TestCheckRateLimit
# ---------------------------------------------------------------------------


class TestCheckRateLimit:
    async def test_disabled_setting_is_noop_without_redis_call(self):
        mock_redis = AsyncMock()
        with patch("core.rate_limit.settings", _make_settings(rate_limit_enabled=False)):
            with patch("core.rate_limit.get_redis", return_value=mock_redis):
                await mod.check_rate_limit("test:key")
        mock_redis.incr.assert_not_called()

    async def test_first_request_sets_expiry_window_plus_one(self):
        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=1)
        mock_redis.ttl = AsyncMock(return_value=300)
        with patch("core.rate_limit.settings", _make_settings(rate_limit_window=300, rate_limit_login=5)):
            with patch("core.rate_limit.get_redis", return_value=mock_redis):
                await mod.check_rate_limit("test:first")
        mock_redis.expire.assert_called_once_with("ratelimit:test:first", 301)

    async def test_under_limit_does_not_raise_exception(self):
        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=3)
        with patch("core.rate_limit.settings", _make_settings(rate_limit_login=5, rate_limit_window=300)):
            with patch("core.rate_limit.get_redis", return_value=mock_redis):
                await mod.check_rate_limit("test:under")  # must not raise

    async def test_over_limit_raises_http_429(self):
        from fastapi import HTTPException

        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=6)
        mock_redis.ttl = AsyncMock(return_value=120)
        with patch("core.rate_limit.settings", _make_settings(rate_limit_login=5, rate_limit_window=300)):
            with patch("core.rate_limit.get_redis", return_value=mock_redis):
                with pytest.raises(HTTPException) as exc_info:
                    await mod.check_rate_limit("test:over")
        assert exc_info.value.status_code == 429
        assert "120" in exc_info.value.detail

    async def test_custom_max_and_window_override_defaults(self):
        from fastapi import HTTPException

        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=11)
        mock_redis.ttl = AsyncMock(return_value=60)
        with patch("core.rate_limit.settings", _make_settings(rate_limit_login=5, rate_limit_window=300)):
            with patch("core.rate_limit.get_redis", return_value=mock_redis):
                with pytest.raises(HTTPException) as exc_info:
                    await mod.check_rate_limit("test:custom", max_requests=10, window=60)
        assert exc_info.value.status_code == 429


# ---------------------------------------------------------------------------
# TestGetClientIp
# ---------------------------------------------------------------------------


class TestGetClientIp:
    def setup_method(self):
        mod._trusted_networks.cache_clear()

    def teardown_method(self):
        mod._trusted_networks.cache_clear()

    def test_no_forwarded_header_returns_peer_ip(self):
        req = _make_request(host="1.2.3.4", headers={})
        with patch("core.rate_limit.settings", _make_settings(trusted_proxies="")):
            result = mod.get_client_ip(req)
        assert result == "1.2.3.4"

    def test_trusted_proxy_forwards_first_ip_in_header(self):
        req = _make_request(host="10.0.0.1", headers={"x-forwarded-for": "203.0.113.5, 10.0.0.1"})
        with patch("core.rate_limit.settings", _make_settings(trusted_proxies="10.0.0.0/8")):
            result = mod.get_client_ip(req)
        assert result == "203.0.113.5"

    def test_untrusted_proxy_ignores_forwarded_header(self):
        req = _make_request(host="5.5.5.5", headers={"x-forwarded-for": "203.0.113.5"})
        with patch("core.rate_limit.settings", _make_settings(trusted_proxies="10.0.0.0/8")):
            result = mod.get_client_ip(req)
        assert result == "5.5.5.5"

    def test_no_client_object_returns_unknown(self):
        req = MagicMock()
        req.client = None
        req.headers = {}
        with patch("core.rate_limit.settings", _make_settings(trusted_proxies="")):
            result = mod.get_client_ip(req)
        assert result == "unknown"


# ---------------------------------------------------------------------------
# TestIsPrivate
# ---------------------------------------------------------------------------


class TestIsPrivate:
    def test_10_x_address_is_private(self):
        assert mod._is_private("10.1.2.3") is True

    def test_172_16_x_address_is_private(self):
        assert mod._is_private("172.20.0.1") is True

    def test_192_168_x_address_is_private(self):
        assert mod._is_private("192.168.1.1") is True

    def test_public_ip_is_not_private(self):
        assert mod._is_private("8.8.8.8") is False


# ---------------------------------------------------------------------------
# TestRateLimitMiddleware
# ---------------------------------------------------------------------------


class TestRateLimitMiddleware:
    def setup_method(self):
        mod._trusted_networks.cache_clear()

    def teardown_method(self):
        mod._trusted_networks.cache_clear()

    async def test_health_check_bypasses_redis_entirely(self):
        """Requests to /api/health should skip rate limiting and not touch Redis."""
        from starlette.applications import Starlette

        app = Starlette()
        middleware = mod.RateLimitMiddleware(app)
        mock_response = MagicMock()
        call_next = AsyncMock(return_value=mock_response)
        req = _make_request(host="1.2.3.4", path="/api/health")

        mock_redis = AsyncMock()
        with patch("core.rate_limit.settings", _make_settings(rate_limit_enabled=True)):
            with patch("core.rate_limit.get_redis", return_value=mock_redis):
                await middleware.dispatch(req, call_next)

        call_next.assert_awaited_once_with(req)
        mock_redis.incr.assert_not_called()

    async def test_private_ip_bypasses_rate_limit(self):
        """LAN/private IP addresses should call_next without hitting Redis."""
        from starlette.applications import Starlette

        app = Starlette()
        middleware = mod.RateLimitMiddleware(app)
        mock_response = MagicMock()
        call_next = AsyncMock(return_value=mock_response)
        req = _make_request(host="192.168.1.10", path="/api/library/", headers={})

        mock_redis = AsyncMock()
        with patch("core.rate_limit.settings", _make_settings(rate_limit_enabled=True, trusted_proxies="")):
            with patch("core.rate_limit.get_redis", return_value=mock_redis):
                await middleware.dispatch(req, call_next)

        call_next.assert_awaited_once_with(req)
        mock_redis.incr.assert_not_called()

    async def test_over_global_limit_returns_429_without_calling_next(self):
        """When global IP counter exceeds 600/min, return 429 JSONResponse."""
        from starlette.applications import Starlette

        app = Starlette()
        middleware = mod.RateLimitMiddleware(app)
        call_next = AsyncMock()
        req = _make_request(host="203.0.113.1", path="/api/library/", headers={})

        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=601)  # exceeds _GLOBAL_RATE_LIMIT=600
        mock_redis.expire = AsyncMock()
        mock_redis.ttl = AsyncMock(return_value=45)

        with patch("core.rate_limit.settings", _make_settings(rate_limit_enabled=True, trusted_proxies="")):
            with patch("core.rate_limit.get_redis", return_value=mock_redis):
                resp = await middleware.dispatch(req, call_next)

        assert resp.status_code == 429
        call_next.assert_not_awaited()
