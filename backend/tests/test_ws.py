"""
Tests for WebSocket endpoint (/api/ws) — routers/ws.py

Strategy:
- Unit-test _validate_ws_session, _pubsub_listener, _ping_loop, _ws_receiver
  as standalone async functions (no real WebSocket connection).
- Integration-style WebSocket tests using starlette.testclient.TestClient.
  conftest.py already sets up the _app with all patches; we import it here.
- Mock get_redis / get_pubsub / get_system_alerts / clear_system_alerts so
  the long-running tasks exit quickly.

Coverage targets:
  Lines 20-36  — _validate_ws_session
  Lines 41-69  — _pubsub_listener
  Lines 74-88  — _ping_loop
  Lines 93-97  — _ws_receiver
  Lines 111-137 — websocket_endpoint
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pubsub_mock(messages=None):
    """
    Build a mock pubsub object that yields a finite sequence of messages
    then raises CancelledError to terminate _pubsub_listener naturally.
    """
    if messages is None:
        messages = []

    async def _listen():
        for msg in messages:
            yield msg
        raise asyncio.CancelledError

    pubsub = MagicMock()
    pubsub.subscribe = AsyncMock()
    pubsub.unsubscribe = AsyncMock()
    pubsub.aclose = AsyncMock()
    pubsub.listen = _listen
    return pubsub


def _redis_with_session(user_id: str = "1", role: str = "admin"):
    """Return an AsyncMock Redis that returns a valid session for user_id."""
    redis = AsyncMock()
    session_data = json.dumps({"role": role}).encode()
    redis.get = AsyncMock(return_value=session_data)
    return redis


def _redis_no_session():
    """Return an AsyncMock Redis that returns None (session not found)."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    return redis


# ---------------------------------------------------------------------------
# Unit tests for _validate_ws_session
# ---------------------------------------------------------------------------


class TestValidateWsSession:
    """Unit-test _validate_ws_session without a real WebSocket connection."""

    async def test_validate_ws_session_no_cookie_returns_none(self):
        """Missing vault_session cookie → None returned immediately."""
        from routers.ws import _validate_ws_session

        ws = MagicMock()
        ws.cookies = {}

        result = await _validate_ws_session(ws)
        assert result is None

    async def test_validate_ws_session_valid_cookie_returns_tuple(self):
        """Valid cookie with Redis session → (user_id_str, role) tuple."""
        from routers.ws import _validate_ws_session

        ws = MagicMock()
        ws.cookies = {"vault_session": "1:abc123"}

        redis = _redis_with_session(user_id="1", role="member")
        with patch("routers.ws.get_redis", return_value=redis):
            result = await _validate_ws_session(ws)

        assert result == ("1", "member")
        redis.get.assert_called_once_with("session:1:abc123")

    async def test_validate_ws_session_redis_returns_none_returns_none(self):
        """Redis returns None (expired/missing session) → None returned."""
        from routers.ws import _validate_ws_session

        ws = MagicMock()
        ws.cookies = {"vault_session": "2:deadbeef"}

        redis = _redis_no_session()
        with patch("routers.ws.get_redis", return_value=redis):
            result = await _validate_ws_session(ws)

        assert result is None

    async def test_validate_ws_session_malformed_cookie_returns_none(self):
        """Cookie without ':' separator raises ValueError → None returned."""
        from routers.ws import _validate_ws_session

        ws = MagicMock()
        ws.cookies = {"vault_session": "no-colon-here"}

        # split(":", 1) on "no-colon-here" returns a single-element list
        # so unpacking into (user_id_str, token) raises ValueError → caught → None.
        result = await _validate_ws_session(ws)

        assert result is None

    async def test_validate_ws_session_redis_connection_error_returns_none(self):
        """ConnectionError from Redis → caught, None returned."""
        from routers.ws import _validate_ws_session

        ws = MagicMock()
        ws.cookies = {"vault_session": "1:tokenxyz"}

        redis = AsyncMock()
        redis.get = AsyncMock(side_effect=ConnectionError("refused"))
        with patch("routers.ws.get_redis", return_value=redis):
            result = await _validate_ws_session(ws)

        assert result is None

    async def test_validate_ws_session_invalid_json_defaults_to_viewer_role(self):
        """Redis returns non-JSON bytes → role defaults to 'viewer'."""
        from routers.ws import _validate_ws_session

        ws = MagicMock()
        ws.cookies = {"vault_session": "3:tok"}

        redis = AsyncMock()
        redis.get = AsyncMock(return_value=b"not-valid-json")
        with patch("routers.ws.get_redis", return_value=redis):
            result = await _validate_ws_session(ws)

        assert result == ("3", "viewer")

    async def test_validate_ws_session_raw_string_data_decoded_correctly(self):
        """Redis returns str instead of bytes → still parsed correctly."""
        from routers.ws import _validate_ws_session

        ws = MagicMock()
        ws.cookies = {"vault_session": "5:strtoken"}

        redis = AsyncMock()
        redis.get = AsyncMock(return_value=json.dumps({"role": "admin"}))
        with patch("routers.ws.get_redis", return_value=redis):
            result = await _validate_ws_session(ws)

        assert result == ("5", "admin")

    async def test_validate_ws_session_admin_role_returned(self):
        """Admin role stored in Redis → returned in tuple."""
        from routers.ws import _validate_ws_session

        ws = MagicMock()
        ws.cookies = {"vault_session": "1:admintoken"}

        redis = _redis_with_session(role="admin")
        with patch("routers.ws.get_redis", return_value=redis):
            result = await _validate_ws_session(ws)

        assert result is not None
        assert result[1] == "admin"


# ---------------------------------------------------------------------------
# Unit tests for _pubsub_listener
# ---------------------------------------------------------------------------


class TestPubsubListener:
    """Direct unit tests for _pubsub_listener."""

    async def test_pubsub_listener_forwards_message_bytes(self):
        """Bytes payload in new Event format → decoded, translated, and sent to WebSocket."""
        from routers.ws import _pubsub_listener

        ws = AsyncMock()
        event = json.dumps({
            "event_type": "download.completed",
            "actor_user_id": 1,
            "resource_type": "download_job",
            "resource_id": "abc123",
            "data": {"_legacy_type": "job_update", "job_id": "abc123", "status": "done", "progress": None},
        })
        pubsub = _make_pubsub_mock(messages=[
            {"type": "message", "data": event.encode()},
        ])

        with patch("routers.ws.get_pubsub", return_value=pubsub):
            with pytest.raises(asyncio.CancelledError):
                await _pubsub_listener(ws, user_id="1", role="admin")

        ws.send_text.assert_called_once()
        sent = json.loads(ws.send_text.call_args[0][0])
        assert sent["type"] == "job_update"
        assert sent["job_id"] == "abc123"
        assert sent["status"] == "done"

    async def test_pubsub_listener_forwards_message_str(self):
        """String payload in new Event format → translated and sent to WebSocket."""
        from routers.ws import _pubsub_listener

        ws = AsyncMock()
        event = json.dumps({
            "event_type": "gallery.updated",
            "actor_user_id": 1,
            "resource_type": "gallery",
            "resource_id": 5,
            "data": {},
        })
        pubsub = _make_pubsub_mock(messages=[
            {"type": "message", "data": event},
        ])

        with patch("routers.ws.get_pubsub", return_value=pubsub):
            with pytest.raises(asyncio.CancelledError):
                await _pubsub_listener(ws, user_id="1", role="admin")

        ws.send_text.assert_called_once()
        sent = json.loads(ws.send_text.call_args[0][0])
        assert sent["type"] == "gallery.updated"
        assert sent["event_type"] == "gallery.updated"

    async def test_pubsub_listener_skips_non_message_type(self):
        """subscribe-type messages → not forwarded to WebSocket."""
        from routers.ws import _pubsub_listener

        ws = AsyncMock()
        pubsub = _make_pubsub_mock(messages=[
            {"type": "subscribe", "data": b"events:all"},
        ])

        with patch("routers.ws.get_pubsub", return_value=pubsub):
            with pytest.raises(asyncio.CancelledError):
                await _pubsub_listener(ws, user_id="1", role="admin")

        ws.send_text.assert_not_called()

    async def test_pubsub_listener_filters_other_user_events_for_non_admin(self):
        """Non-admin user → events for other users are dropped."""
        from routers.ws import _pubsub_listener

        ws = AsyncMock()
        other_user_event = json.dumps({
            "event_type": "download.started",
            "actor_user_id": 99,
            "data": {"_legacy_type": "job_update", "status": "running"},
        })
        pubsub = _make_pubsub_mock(messages=[
            {"type": "message", "data": other_user_event.encode()},
        ])

        with patch("routers.ws.get_pubsub", return_value=pubsub):
            with pytest.raises(asyncio.CancelledError):
                await _pubsub_listener(ws, user_id="1", role="member")

        ws.send_text.assert_not_called()

    async def test_pubsub_listener_allows_own_events_for_non_admin(self):
        """Non-admin user → events for their own actor_user_id pass through."""
        from routers.ws import _pubsub_listener

        ws = AsyncMock()
        own_event = json.dumps({
            "event_type": "download.started",
            "actor_user_id": 1,
            "data": {"_legacy_type": "job_update", "status": "running"},
        })
        pubsub = _make_pubsub_mock(messages=[
            {"type": "message", "data": own_event.encode()},
        ])

        with patch("routers.ws.get_pubsub", return_value=pubsub):
            with pytest.raises(asyncio.CancelledError):
                await _pubsub_listener(ws, user_id="1", role="member")

        ws.send_text.assert_called_once()

    async def test_pubsub_listener_allows_null_user_id_broadcast_for_non_admin(self):
        """Events with actor_user_id=None are broadcast to all users, including non-admin."""
        from routers.ws import _pubsub_listener

        ws = AsyncMock()
        broadcast_event = json.dumps({
            "event_type": "gallery.updated",
            "actor_user_id": None,
            "data": {},
        })
        pubsub = _make_pubsub_mock(messages=[
            {"type": "message", "data": broadcast_event.encode()},
        ])

        with patch("routers.ws.get_pubsub", return_value=pubsub):
            with pytest.raises(asyncio.CancelledError):
                await _pubsub_listener(ws, user_id="2", role="member")

        ws.send_text.assert_called_once()

    async def test_pubsub_listener_admin_receives_all_events(self):
        """Admin role → receives events for any actor_user_id."""
        from routers.ws import _pubsub_listener

        ws = AsyncMock()
        other_event = json.dumps({
            "event_type": "download.started",
            "actor_user_id": 42,
            "data": {"_legacy_type": "job_update", "status": "running"},
        })
        pubsub = _make_pubsub_mock(messages=[
            {"type": "message", "data": other_event.encode()},
        ])

        with patch("routers.ws.get_pubsub", return_value=pubsub):
            with pytest.raises(asyncio.CancelledError):
                await _pubsub_listener(ws, user_id="1", role="admin")

        ws.send_text.assert_called_once()

    async def test_pubsub_listener_cleans_up_on_cancel(self):
        """unsubscribe and aclose are always called on exit."""
        from routers.ws import _pubsub_listener

        ws = AsyncMock()
        pubsub = _make_pubsub_mock(messages=[])

        with patch("routers.ws.get_pubsub", return_value=pubsub):
            with pytest.raises(asyncio.CancelledError):
                await _pubsub_listener(ws, user_id="1", role="admin")

        pubsub.unsubscribe.assert_called_once_with("events:all")
        pubsub.aclose.assert_called_once()

    async def test_pubsub_listener_ignores_malformed_json_in_filter(self):
        """Non-JSON event data for non-admin → dropped (cannot parse actor_user_id)."""
        from routers.ws import _pubsub_listener

        ws = AsyncMock()
        # Non-JSON data: the except block drops the message for non-admin users
        # because it cannot verify ownership.
        pubsub = _make_pubsub_mock(messages=[
            {"type": "message", "data": b"not-json"},
        ])

        with patch("routers.ws.get_pubsub", return_value=pubsub):
            with pytest.raises(asyncio.CancelledError):
                await _pubsub_listener(ws, user_id="1", role="member")

        # Non-JSON + non-admin → dropped (only admin receives non-JSON as-is)
        ws.send_text.assert_not_called()

    async def test_pubsub_listener_admin_receives_malformed_json_as_is(self):
        """Non-JSON event data for admin → forwarded as-is (backward compat)."""
        from routers.ws import _pubsub_listener

        ws = AsyncMock()
        pubsub = _make_pubsub_mock(messages=[
            {"type": "message", "data": b"not-json"},
        ])

        with patch("routers.ws.get_pubsub", return_value=pubsub):
            with pytest.raises(asyncio.CancelledError):
                await _pubsub_listener(ws, user_id="1", role="admin")

        ws.send_text.assert_called_once_with("not-json")

    async def test_pubsub_listener_subscribes_to_events_all(self):
        """pubsub.subscribe is called with 'events:all' channel."""
        from routers.ws import _pubsub_listener

        ws = AsyncMock()
        pubsub = _make_pubsub_mock(messages=[])

        with patch("routers.ws.get_pubsub", return_value=pubsub):
            with pytest.raises(asyncio.CancelledError):
                await _pubsub_listener(ws, user_id="1", role="admin")

        pubsub.subscribe.assert_called_once_with("events:all")

    async def test_pubsub_listener_translates_job_update_to_legacy_format(self):
        """Event with _legacy_type='job_update' is translated to legacy WS format."""
        from routers.ws import _pubsub_listener

        ws = AsyncMock()
        event = json.dumps({
            "event_type": "download.completed",
            "actor_user_id": 3,
            "resource_type": "download_job",
            "resource_id": "job-xyz",
            "data": {
                "_legacy_type": "job_update",
                "job_id": "job-xyz",
                "status": "done",
                "progress": {"current": 10, "total": 10},
            },
        })
        pubsub = _make_pubsub_mock(messages=[
            {"type": "message", "data": event.encode()},
        ])

        with patch("routers.ws.get_pubsub", return_value=pubsub):
            with pytest.raises(asyncio.CancelledError):
                await _pubsub_listener(ws, user_id="3", role="member")

        ws.send_text.assert_called_once()
        sent = json.loads(ws.send_text.call_args[0][0])
        assert sent["type"] == "job_update"
        assert sent["job_id"] == "job-xyz"
        assert sent["status"] == "done"
        assert sent["progress"] == {"current": 10, "total": 10}
        assert sent["user_id"] == 3

    async def test_pubsub_listener_translates_subscription_checked_to_legacy_format(self):
        """Event with _legacy_type='subscription_checked' is translated to legacy WS format."""
        from routers.ws import _pubsub_listener

        ws = AsyncMock()
        event = json.dumps({
            "event_type": "subscription.checked",
            "actor_user_id": 2,
            "resource_type": "subscription",
            "resource_id": "sub-42",
            "data": {
                "_legacy_type": "subscription_checked",
                "sub_id": "sub-42",
                "status": "completed",
                "job_id": "job-999",
                "new_works": 5,
            },
        })
        pubsub = _make_pubsub_mock(messages=[
            {"type": "message", "data": event.encode()},
        ])

        with patch("routers.ws.get_pubsub", return_value=pubsub):
            with pytest.raises(asyncio.CancelledError):
                await _pubsub_listener(ws, user_id="2", role="member")

        ws.send_text.assert_called_once()
        sent = json.loads(ws.send_text.call_args[0][0])
        assert sent["type"] == "subscription_checked"
        assert sent["sub_id"] == "sub-42"
        assert sent["status"] == "completed"
        assert sent["job_id"] == "job-999"
        assert sent["new_works"] == 5
        assert sent["user_id"] == 2

    async def test_pubsub_listener_passes_through_new_event_types(self):
        """Events without _legacy_type are forwarded with event_type field intact."""
        from routers.ws import _pubsub_listener

        ws = AsyncMock()
        event = json.dumps({
            "event_type": "gallery.tagged",
            "actor_user_id": 1,
            "resource_type": "gallery",
            "resource_id": 99,
            "data": {"tags": ["artist:foo", "parody:bar"]},
        })
        pubsub = _make_pubsub_mock(messages=[
            {"type": "message", "data": event.encode()},
        ])

        with patch("routers.ws.get_pubsub", return_value=pubsub):
            with pytest.raises(asyncio.CancelledError):
                await _pubsub_listener(ws, user_id="1", role="admin")

        ws.send_text.assert_called_once()
        sent = json.loads(ws.send_text.call_args[0][0])
        assert sent["type"] == "gallery.tagged"
        assert sent["event_type"] == "gallery.tagged"
        assert sent["resource_type"] == "gallery"
        assert sent["resource_id"] == 99
        assert sent["data"] == {"tags": ["artist:foo", "parody:bar"]}


# ---------------------------------------------------------------------------
# Unit tests for _ping_loop
# ---------------------------------------------------------------------------


class TestPingLoop:
    """Direct unit tests for _ping_loop."""

    async def test_ping_loop_sends_ping_message(self):
        """_ping_loop sends a ping JSON message on each iteration."""
        from routers.ws import _ping_loop

        ws = AsyncMock()

        async def _mock_sleep(t):
            raise asyncio.CancelledError

        with (
            patch("routers.ws.get_system_alerts", new_callable=AsyncMock, return_value=[]),
            patch("routers.ws.clear_system_alerts", new_callable=AsyncMock),
            patch("asyncio.sleep", side_effect=_mock_sleep),
        ):
            with pytest.raises(asyncio.CancelledError):
                await _ping_loop(ws)

        ws.send_json.assert_called_once()
        call_args = ws.send_json.call_args[0][0]
        assert call_args["type"] == "ping"
        assert "ts" in call_args

    async def test_ping_loop_sends_alert_messages(self):
        """When system alerts are present, they are sent before the ping."""
        from routers.ws import _ping_loop

        ws = AsyncMock()
        alerts = ["disk almost full", "service degraded"]

        async def _mock_sleep(t):
            raise asyncio.CancelledError

        with (
            patch("routers.ws.get_system_alerts", new_callable=AsyncMock, return_value=alerts),
            patch("routers.ws.clear_system_alerts", new_callable=AsyncMock),
            patch("asyncio.sleep", side_effect=_mock_sleep),
        ):
            with pytest.raises(asyncio.CancelledError):
                await _ping_loop(ws)

        # 2 alert sends + 1 ping send = 3 calls
        assert ws.send_json.call_count == 3
        alert_calls = [c[0][0] for c in ws.send_json.call_args_list]
        assert alert_calls[0] == {"type": "alert", "message": "disk almost full"}
        assert alert_calls[1] == {"type": "alert", "message": "service degraded"}
        assert alert_calls[2]["type"] == "ping"

    async def test_ping_loop_clears_alerts_after_sending(self):
        """clear_system_alerts is called after sending all alert messages."""
        from routers.ws import _ping_loop

        ws = AsyncMock()
        clear_mock = AsyncMock()

        async def _mock_sleep(t):
            raise asyncio.CancelledError

        with (
            patch("routers.ws.get_system_alerts", new_callable=AsyncMock, return_value=["alert!"]),
            patch("routers.ws.clear_system_alerts", clear_mock),
            patch("asyncio.sleep", side_effect=_mock_sleep),
        ):
            with pytest.raises(asyncio.CancelledError):
                await _ping_loop(ws)

        clear_mock.assert_called_once()

    async def test_ping_loop_no_alerts_skips_clear(self):
        """When no alerts, clear_system_alerts is not called."""
        from routers.ws import _ping_loop

        ws = AsyncMock()
        clear_mock = AsyncMock()

        async def _mock_sleep(t):
            raise asyncio.CancelledError

        with (
            patch("routers.ws.get_system_alerts", new_callable=AsyncMock, return_value=[]),
            patch("routers.ws.clear_system_alerts", clear_mock),
            patch("asyncio.sleep", side_effect=_mock_sleep),
        ):
            with pytest.raises(asyncio.CancelledError):
                await _ping_loop(ws)

        clear_mock.assert_not_called()

    async def test_ping_loop_runs_every_2_seconds(self):
        """asyncio.sleep is called with 2 seconds on each loop iteration."""
        from routers.ws import _ping_loop

        ws = AsyncMock()
        sleep_args = []

        async def _mock_sleep(t):
            sleep_args.append(t)
            if len(sleep_args) >= 1:
                raise asyncio.CancelledError

        with (
            patch("routers.ws.get_system_alerts", new_callable=AsyncMock, return_value=[]),
            patch("routers.ws.clear_system_alerts", new_callable=AsyncMock),
            patch("asyncio.sleep", side_effect=_mock_sleep),
        ):
            with pytest.raises(asyncio.CancelledError):
                await _ping_loop(ws)

        assert sleep_args[0] == 2


# ---------------------------------------------------------------------------
# Unit tests for _ws_receiver
# ---------------------------------------------------------------------------


class TestWsReceiver:
    """Direct unit tests for _ws_receiver."""

    async def test_ws_receiver_loops_on_receive(self):
        """_ws_receiver calls ws.receive() repeatedly until cancelled."""
        from routers.ws import _ws_receiver

        call_count = 0

        async def _fake_receive():
            nonlocal call_count
            call_count += 1
            if call_count >= 3:
                raise asyncio.CancelledError
            return {"type": "websocket.receive", "text": "hello"}

        ws = AsyncMock()
        ws.receive = _fake_receive

        with pytest.raises(asyncio.CancelledError):
            await _ws_receiver(ws)

        assert call_count == 3

    async def test_ws_receiver_raises_on_websocket_disconnect(self):
        """WebSocketDisconnect propagates up from _ws_receiver."""
        from fastapi import WebSocketDisconnect
        from routers.ws import _ws_receiver

        ws = AsyncMock()
        ws.receive = AsyncMock(side_effect=WebSocketDisconnect(code=1000))

        with pytest.raises(WebSocketDisconnect):
            await _ws_receiver(ws)

    async def test_ws_receiver_raises_on_runtime_error(self):
        """RuntimeError from receive propagates up from _ws_receiver."""
        from routers.ws import _ws_receiver

        ws = AsyncMock()
        ws.receive = AsyncMock(side_effect=RuntimeError("connection lost"))

        with pytest.raises(RuntimeError):
            await _ws_receiver(ws)


# ---------------------------------------------------------------------------
# Integration-style WebSocket endpoint tests via starlette TestClient
# ---------------------------------------------------------------------------


class TestWebsocketEndpoint:
    """
    End-to-end WebSocket tests using starlette.testclient.TestClient.

    TestClient.websocket_connect() is a sync context manager that handles
    the WebSocket handshake and gives access to send/receive methods.

    The app instance is imported from the already-patched conftest module
    to avoid double-initialisation.
    """

    @pytest.fixture(autouse=True)
    def _get_app(self):
        """Fetch _app from the already-initialised conftest module."""
        import tests.conftest as _conftest
        # conftest exposes _app at module level after all patches are applied.
        self._app = _conftest._app

    def _make_client(self):
        from starlette.testclient import TestClient
        return TestClient(self._app, raise_server_exceptions=False)

    def _make_pubsub_blocking(self):
        """Pubsub that never yields — stays blocked until the connection closes."""
        async def _listen_never():
            await asyncio.sleep(10)
            # Unreachable; makes it an async generator
            yield  # pragma: no cover

        pubsub = MagicMock()
        pubsub.subscribe = AsyncMock()
        pubsub.unsubscribe = AsyncMock()
        pubsub.aclose = AsyncMock()
        pubsub.listen = _listen_never
        return pubsub

    def test_ws_connect_without_cookie_is_rejected(self):
        """No vault_session cookie → server closes before accept (code 4001)."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        with (
            patch("routers.ws.get_redis", return_value=mock_redis),
        ):
            client = self._make_client()
            # starlette TestClient raises WebSocketDisconnect or similar when
            # the server closes without accepting.
            with pytest.raises(Exception):
                with client.websocket_connect("/api/ws") as ws:
                    ws.receive_json()

    def test_ws_connect_with_invalid_session_is_rejected(self):
        """vault_session set but Redis returns None → authentication fails."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        with (
            patch("routers.ws.get_redis", return_value=mock_redis),
        ):
            client = self._make_client()
            with pytest.raises(Exception):
                with client.websocket_connect(
                    "/api/ws", cookies={"vault_session": "1:badtoken"}
                ) as ws:
                    ws.receive_json()

    def test_ws_connect_authed_admin_receives_ping(self):
        """Valid admin session → connection accepted and ping message received."""
        session_data = json.dumps({"role": "admin"}).encode()
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=session_data)
        pubsub = self._make_pubsub_blocking()

        with (
            patch("routers.ws.get_redis", return_value=mock_redis),
            patch("routers.ws.get_pubsub", return_value=pubsub),
            patch("routers.ws.get_system_alerts", new_callable=AsyncMock, return_value=[]),
            patch("routers.ws.clear_system_alerts", new_callable=AsyncMock),
        ):
            client = self._make_client()
            with client.websocket_connect(
                "/api/ws", cookies={"vault_session": "1:validtoken"}
            ) as ws:
                msg = ws.receive_json()

        assert msg["type"] == "ping"
        assert "ts" in msg

    def test_ws_connect_authed_member_receives_ping(self):
        """Valid member session → connection accepted and ping message received."""
        session_data = json.dumps({"role": "member"}).encode()
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=session_data)
        pubsub = self._make_pubsub_blocking()

        with (
            patch("routers.ws.get_redis", return_value=mock_redis),
            patch("routers.ws.get_pubsub", return_value=pubsub),
            patch("routers.ws.get_system_alerts", new_callable=AsyncMock, return_value=[]),
            patch("routers.ws.clear_system_alerts", new_callable=AsyncMock),
        ):
            client = self._make_client()
            with client.websocket_connect(
                "/api/ws", cookies={"vault_session": "2:membertoken"}
            ) as ws:
                msg = ws.receive_json()

        assert msg["type"] == "ping"

    def test_ws_connect_authed_viewer_receives_ping(self):
        """Valid viewer session → connection accepted and ping message received."""
        session_data = json.dumps({"role": "viewer"}).encode()
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=session_data)
        pubsub = self._make_pubsub_blocking()

        with (
            patch("routers.ws.get_redis", return_value=mock_redis),
            patch("routers.ws.get_pubsub", return_value=pubsub),
            patch("routers.ws.get_system_alerts", new_callable=AsyncMock, return_value=[]),
            patch("routers.ws.clear_system_alerts", new_callable=AsyncMock),
        ):
            client = self._make_client()
            with client.websocket_connect(
                "/api/ws", cookies={"vault_session": "3:viewertoken"}
            ) as ws:
                msg = ws.receive_json()

        assert msg["type"] == "ping"

    def test_ws_connect_authed_receives_alert_then_ping(self):
        """When system alerts exist, they arrive before the ping message."""
        session_data = json.dumps({"role": "admin"}).encode()
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=session_data)
        pubsub = self._make_pubsub_blocking()

        with (
            patch("routers.ws.get_redis", return_value=mock_redis),
            patch("routers.ws.get_pubsub", return_value=pubsub),
            patch("routers.ws.get_system_alerts", new_callable=AsyncMock, return_value=["low disk"]),
            patch("routers.ws.clear_system_alerts", new_callable=AsyncMock),
        ):
            client = self._make_client()
            with client.websocket_connect(
                "/api/ws", cookies={"vault_session": "1:validtoken"}
            ) as ws:
                alert_msg = ws.receive_json()
                ping_msg = ws.receive_json()

        assert alert_msg == {"type": "alert", "message": "low disk"}
        assert ping_msg["type"] == "ping"

    def test_ws_connect_authed_receives_multiple_alerts(self):
        """Multiple alerts are all sent before the ping message."""
        session_data = json.dumps({"role": "admin"}).encode()
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=session_data)
        pubsub = self._make_pubsub_blocking()
        alerts = ["alert one", "alert two", "alert three"]

        with (
            patch("routers.ws.get_redis", return_value=mock_redis),
            patch("routers.ws.get_pubsub", return_value=pubsub),
            patch("routers.ws.get_system_alerts", new_callable=AsyncMock, return_value=alerts),
            patch("routers.ws.clear_system_alerts", new_callable=AsyncMock),
        ):
            client = self._make_client()
            with client.websocket_connect(
                "/api/ws", cookies={"vault_session": "1:validtoken"}
            ) as ws:
                msgs = [ws.receive_json() for _ in range(4)]

        assert msgs[0] == {"type": "alert", "message": "alert one"}
        assert msgs[1] == {"type": "alert", "message": "alert two"}
        assert msgs[2] == {"type": "alert", "message": "alert three"}
        assert msgs[3]["type"] == "ping"


# ---------------------------------------------------------------------------
# Edge case tests — uncovered lines 62-64, 86-88, 111-137
# ---------------------------------------------------------------------------


class TestPubsubListenerErrorPath:
    """Cover lines 62-64: generic Exception in _pubsub_listener is re-raised."""

    async def test_pubsub_listener_reraises_generic_exception(self):
        """A non-CancelledError/WebSocketDisconnect exception from pubsub is re-raised."""
        from routers.ws import _pubsub_listener

        ws = AsyncMock()

        # Build an async generator that raises a generic RuntimeError mid-iteration
        async def _listen_raises():
            yield {"type": "subscribe", "data": b"ok"}
            raise RuntimeError("pubsub broken")

        pubsub = MagicMock()
        pubsub.subscribe = AsyncMock()
        pubsub.unsubscribe = AsyncMock()
        pubsub.aclose = AsyncMock()
        pubsub.listen = _listen_raises

        with patch("routers.ws.get_pubsub", return_value=pubsub):
            with pytest.raises(RuntimeError, match="pubsub broken"):
                await _pubsub_listener(ws, user_id="1", role="admin")

        # Cleanup is still called even on generic exception
        pubsub.unsubscribe.assert_called_once_with("events:all")
        pubsub.aclose.assert_called_once()

    async def test_pubsub_listener_reraises_os_error(self):
        """OSError from pubsub is re-raised after cleanup (covers line 62-64)."""
        from routers.ws import _pubsub_listener

        ws = AsyncMock()

        async def _listen_os_error():
            raise OSError("connection reset by peer")
            yield  # pragma: no cover  # make it an async generator

        pubsub = MagicMock()
        pubsub.subscribe = AsyncMock()
        pubsub.unsubscribe = AsyncMock()
        pubsub.aclose = AsyncMock()
        pubsub.listen = _listen_os_error

        with patch("routers.ws.get_pubsub", return_value=pubsub):
            with pytest.raises(OSError):
                await _pubsub_listener(ws, user_id="1", role="admin")

        pubsub.aclose.assert_called_once()


class TestPingLoopErrorPath:
    """Cover lines 86-88: ConnectionError / RuntimeError in _ping_loop is re-raised."""

    async def test_ping_loop_reraises_connection_error_from_send_json(self):
        """ConnectionError from ws.send_json is caught and re-raised (lines 86-88)."""
        from routers.ws import _ping_loop

        ws = AsyncMock()
        ws.send_json = AsyncMock(side_effect=ConnectionError("broken pipe"))

        with (
            patch("routers.ws.get_system_alerts", new_callable=AsyncMock, return_value=[]),
            patch("routers.ws.clear_system_alerts", new_callable=AsyncMock),
        ):
            with pytest.raises(ConnectionError, match="broken pipe"):
                await _ping_loop(ws)

    async def test_ping_loop_reraises_runtime_error_from_send_json(self):
        """RuntimeError from ws.send_json is caught and re-raised (lines 86-88)."""
        from routers.ws import _ping_loop

        ws = AsyncMock()
        ws.send_json = AsyncMock(side_effect=RuntimeError("event loop closed"))

        with (
            patch("routers.ws.get_system_alerts", new_callable=AsyncMock, return_value=[]),
            patch("routers.ws.clear_system_alerts", new_callable=AsyncMock),
        ):
            with pytest.raises(RuntimeError, match="event loop closed"):
                await _ping_loop(ws)

    async def test_ping_loop_connection_error_from_alert_send(self):
        """ConnectionError while sending an alert message is also caught and re-raised."""
        from routers.ws import _ping_loop

        call_count = 0

        async def _send_json_side_effect(payload):
            nonlocal call_count
            call_count += 1
            # The first call is for the alert message
            raise ConnectionError("write failed")

        ws = AsyncMock()
        ws.send_json = AsyncMock(side_effect=_send_json_side_effect)

        with (
            patch("routers.ws.get_system_alerts", new_callable=AsyncMock, return_value=["alert!"]),
            patch("routers.ws.clear_system_alerts", new_callable=AsyncMock),
        ):
            with pytest.raises(ConnectionError):
                await _ping_loop(ws)


class TestWebsocketEndpointTaskCleanup:
    """Cover lines 111-137: task cancellation and cleanup in websocket_endpoint."""

    async def test_websocket_endpoint_cancels_pending_tasks_on_first_completion(self):
        """websocket_endpoint cancels all pending tasks when one task finishes first.

        This covers the done/pending cleanup loop (lines 126-135).
        We invoke websocket_endpoint directly with a mock WebSocket object and
        arrange for _ws_receiver to return immediately (simulating client disconnect),
        which makes it the first task to complete and triggers cancellation of the
        remaining two tasks (_pubsub_listener, _ping_loop).
        """
        from routers.ws import websocket_endpoint

        session_data = json.dumps({"role": "admin"})
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=session_data.encode())

        # Mock WebSocket: accept succeeds, receive raises WebSocketDisconnect immediately
        from fastapi import WebSocketDisconnect

        ws = AsyncMock()
        ws.cookies = {"vault_session": "1:tok"}
        ws.client = "127.0.0.1:9999"
        ws.accept = AsyncMock()
        ws.receive = AsyncMock(side_effect=WebSocketDisconnect(code=1000))

        # pubsub blocks until cancelled
        async def _listen_never():
            await asyncio.sleep(60)
            yield  # pragma: no cover

        pubsub = MagicMock()
        pubsub.subscribe = AsyncMock()
        pubsub.unsubscribe = AsyncMock()
        pubsub.aclose = AsyncMock()
        pubsub.listen = _listen_never

        with (
            patch("routers.ws.get_redis", return_value=mock_redis),
            patch("routers.ws.get_pubsub", return_value=pubsub),
            patch("routers.ws.get_system_alerts", new_callable=AsyncMock, return_value=[]),
            patch("routers.ws.clear_system_alerts", new_callable=AsyncMock),
            # Make asyncio.sleep in _ping_loop block, but sleep in _listen_never
            # will be cancelled automatically when _ws_receiver finishes.
        ):
            # The endpoint should return cleanly — not raise
            await websocket_endpoint(ws)

        ws.accept.assert_called_once()
        # pubsub cleanup must have been triggered (called from _pubsub_listener finally)
        pubsub.aclose.assert_called()

    async def test_websocket_endpoint_unauthorized_does_not_accept(self):
        """websocket_endpoint calls ws.close without accept when session is invalid (lines 111-114)."""
        from routers.ws import websocket_endpoint

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)  # no session

        ws = AsyncMock()
        ws.cookies = {"vault_session": "9:badtoken"}
        ws.client = "127.0.0.1:1234"
        ws.close = AsyncMock()
        ws.accept = AsyncMock()

        with patch("routers.ws.get_redis", return_value=mock_redis):
            await websocket_endpoint(ws)

        ws.close.assert_called_once_with(code=4001, reason="Unauthorized")
        ws.accept.assert_not_called()

    async def test_websocket_endpoint_no_cookie_does_not_accept(self):
        """websocket_endpoint calls ws.close without accept when no cookie present."""
        from routers.ws import websocket_endpoint

        ws = AsyncMock()
        ws.cookies = {}
        ws.client = "127.0.0.1:1234"
        ws.close = AsyncMock()
        ws.accept = AsyncMock()

        await websocket_endpoint(ws)

        ws.close.assert_called_once_with(code=4001, reason="Unauthorized")
        ws.accept.assert_not_called()
