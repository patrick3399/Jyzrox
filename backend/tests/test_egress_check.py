"""Tests for the worker's startup egress self-check (IPv6 reachability, Happy Eyeballs)."""

import logging
import sys
from unittest.mock import AsyncMock, patch

import pytest

from worker import egress_check


@pytest.fixture
def caplog_egress(caplog):
    caplog.set_level(logging.DEBUG, logger="worker.egress_check")
    return caplog


def _warnings(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]


# ── IPv6 egress ──


async def test_ipv6_check_without_route_reports_no_route_and_does_not_warn(caplog_egress):
    """IPv4-only deployments (the tracked compose) must stay quiet."""
    connect = AsyncMock()
    with (
        patch.object(egress_check, "_has_ipv6_route", return_value=False),
        patch("asyncio.open_connection", connect),
    ):
        assert await egress_check.check_ipv6_egress() == "no_route"
    connect.assert_not_called()

    with (
        patch.object(egress_check, "check_ipv6_egress", AsyncMock(return_value="no_route")),
        patch.object(egress_check, "check_gdl_happy_eyeballs", AsyncMock(return_value=True)),
    ):
        await egress_check.run_startup_checks()
    assert _warnings(caplog_egress) == []


async def test_ipv6_check_with_route_but_no_answer_warns(caplog_egress):
    with (
        patch.object(egress_check, "_has_ipv6_route", return_value=True),
        patch("asyncio.open_connection", AsyncMock(side_effect=TimeoutError)),
    ):
        assert await egress_check.check_ipv6_egress() == "unreachable"

    with (
        patch.object(egress_check, "check_ipv6_egress", AsyncMock(return_value="unreachable")),
        patch.object(egress_check, "check_gdl_happy_eyeballs", AsyncMock(return_value=True)),
    ):
        await egress_check.run_startup_checks()
    (message,) = _warnings(caplog_egress)
    assert "IPv6" in message and "unreachable" in message


async def test_ipv6_check_ok_when_any_endpoint_answers():
    writer = AsyncMock()
    writer.close = lambda: None
    attempts = []

    async def _connect(host, port):
        attempts.append(host)
        if host == egress_check.IPV6_ENDPOINTS[0][0]:
            raise OSError("unreachable")
        return AsyncMock(), writer

    with (
        patch.object(egress_check, "_has_ipv6_route", return_value=True),
        patch("asyncio.open_connection", _connect),
    ):
        assert await egress_check.check_ipv6_egress() == "ok"
    assert sorted(attempts) == sorted(host for host, _ in egress_check.IPV6_ENDPOINTS)


def test_has_ipv6_route_is_false_when_udp_connect_fails():
    class _NoRoute:
        def __init__(self, *args):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def connect(self, address):
            raise OSError(101, "Network is unreachable")

    with patch("socket.socket", _NoRoute):
        assert egress_check._has_ipv6_route() is False


# ── Happy Eyeballs inside the gallery-dl venv ──


async def test_gdl_check_warns_when_patch_inactive_in_venv(caplog_egress):
    with (
        patch.object(egress_check, "check_ipv6_egress", AsyncMock(return_value="ok")),
        patch.object(egress_check, "check_gdl_happy_eyeballs", AsyncMock(return_value=False)),
    ):
        await egress_check.run_startup_checks()
    (message,) = _warnings(caplog_egress)
    assert "Happy Eyeballs" in message and "not active" in message


async def test_gdl_check_reports_inactive_when_interpreter_exits_with_the_inactive_code(tmp_path):
    fake_python = tmp_path / "python"
    fake_python.write_text(f"#!/bin/sh\nexit {egress_check.INACTIVE_EXIT_CODE}\n")
    fake_python.chmod(0o755)
    assert await egress_check.check_gdl_happy_eyeballs(str(fake_python)) is False


async def test_gdl_check_is_none_when_the_venv_python_is_missing(tmp_path):
    assert await egress_check.check_gdl_happy_eyeballs(str(tmp_path / "missing")) is None


async def test_real_interpreter_reports_happy_eyeballs_active():
    """Runs the exact check against a real interpreter with the real sitecustomize."""
    assert await egress_check.check_gdl_happy_eyeballs(sys.executable) is True


async def test_startup_checks_never_raise(caplog_egress):
    with patch.object(egress_check, "check_ipv6_egress", AsyncMock(side_effect=RuntimeError("boom"))):
        await egress_check.run_startup_checks()
    assert any("boom" in m for m in _warnings(caplog_egress))
