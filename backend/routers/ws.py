"""WebSocket endpoint — real-time download progress and system alerts."""

import asyncio
import contextlib
import datetime
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from core.auth import verify_session
from core.redis_client import get_pubsub, get_redis
from services.cache import clear_system_alerts, get_system_alerts

logger = logging.getLogger(__name__)
router = APIRouter(tags=["websocket"])


async def _validate_ws_session(ws: WebSocket) -> tuple[str, str] | None:
    """Validate session cookie from WebSocket handshake. Returns (user_id, role) or None."""
    vault_session = ws.cookies.get("vault_session")
    if not vault_session:
        return None
    try:
        user_id_str, token = vault_session.split(":", 1)
        raw = await get_redis().get(f"session:{user_id_str}:{token}")
        if not raw:
            return None
        raw_str = raw if isinstance(raw, str) else raw.decode()
        verified = verify_session(raw_str)
        if verified is None:
            return None
        role = "viewer"
        try:
            data = json.loads(verified)
            role = data.get("role", "viewer")
        except (json.JSONDecodeError, TypeError):
            pass
        return (user_id_str, role)
    except (ValueError, ConnectionError, OSError) as exc:
        logger.warning("WS session validation failed: %s", exc)
        return None


def _event_to_ws_message(event_data: dict) -> str:
    """Translate EventBus event format to legacy WebSocket message format.

    Derives the legacy message type from event_type + resource_type rather than
    requiring callers to tag events with internal hints.
    """
    data = event_data.get("data", {})
    actor = event_data.get("actor_user_id")
    event_type = event_data.get("event_type", "")
    resource_type = event_data.get("resource_type")
    resource_id = event_data.get("resource_id")

    if resource_type == "download_job" and event_type.startswith("download."):
        return json.dumps(
            {
                "type": "job_update",
                "job_id": resource_id,
                "status": data.get("status", ""),
                "progress": data.get("progress"),
                "user_id": actor,
            }
        )
    elif event_type == "subscription.checked":
        return json.dumps(
            {
                "type": "subscription_checked",
                "sub_id": resource_id,
                "status": data.get("status", ""),
                "job_id": data.get("job_id"),
                "new_works": data.get("new_works", 0),
                "user_id": actor,
            }
        )
    elif event_type == "semaphore.changed":
        return json.dumps(
            {
                "type": "semaphore_changed",
                "source": data.get("source", ""),
                "action": data.get("action", ""),
                "job_id": data.get("job_id", ""),
            }
        )
    elif event_type.startswith("system."):
        return json.dumps(
            {
                "type": "alert",
                "message": data.get("message", ""),
            }
        )
    else:
        return json.dumps(
            {
                "type": event_type or "unknown",
                "event_type": event_type,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "data": data,
                "user_id": actor,
            }
        )


async def _pubsub_listener(ws: WebSocket, user_id: str, role: str) -> None:
    """Subscribe to events:all and forward messages to the WebSocket client."""
    pubsub = get_pubsub()
    try:
        await pubsub.subscribe("events:all")
        async for message in pubsub.listen():
            if message["type"] == "message":
                data = message["data"]
                if isinstance(data, bytes):
                    data = data.decode()

                # Parse event for filtering
                try:
                    event_data = json.loads(data)
                except json.JSONDecodeError, TypeError:
                    # Non-JSON data — forward as-is (backward compat)
                    if role == "admin":
                        await ws.send_text(data)
                    continue

                # Filter: admin sees all, others see only their own events or broadcasts
                actor_user_id = event_data.get("actor_user_id")
                if role != "admin":
                    if actor_user_id is not None and str(actor_user_id) != user_id:
                        continue

                # Translate to legacy WS format
                ws_message = _event_to_ws_message(event_data)
                await ws.send_text(ws_message)
    except WebSocketDisconnect, asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning("_pubsub_listener error: %s", exc)
        raise
    finally:
        with contextlib.suppress(Exception):
            await pubsub.unsubscribe("events:all")
        with contextlib.suppress(Exception):
            await pubsub.aclose()


async def _ping_loop(ws: WebSocket) -> None:
    """Send alerts and periodic pings to keep the connection alive."""
    try:
        while True:
            alerts = await get_system_alerts()
            if alerts:
                for msg in alerts:
                    await ws.send_json({"type": "alert", "message": msg})
                await clear_system_alerts()

            await ws.send_json({"type": "ping", "ts": datetime.datetime.now(datetime.UTC).isoformat()})
            await asyncio.sleep(2)
    except WebSocketDisconnect, asyncio.CancelledError:
        raise
    except (ConnectionError, RuntimeError) as exc:
        logger.error("_ping_loop error: %s", exc)
        raise


async def _ws_receiver(ws: WebSocket) -> None:
    """Receive messages from the client (detect disconnect)."""
    try:
        while True:
            await ws.receive()
    except WebSocketDisconnect, asyncio.CancelledError, RuntimeError:
        raise


async def _log_stream_listener(ws: WebSocket) -> None:
    """Subscribe to logs:stream, forward log entries to admin WS clients."""
    pubsub = get_pubsub()
    try:
        await pubsub.subscribe("logs:stream")
        async for message in pubsub.listen():
            if message["type"] == "message":
                data = message["data"]
                if isinstance(data, bytes):
                    data = data.decode()
                await ws.send_text(json.dumps({"type": "log_entry", "log": json.loads(data)}))
    except WebSocketDisconnect, asyncio.CancelledError:
        raise
    finally:
        with contextlib.suppress(Exception):
            await pubsub.unsubscribe("logs:stream")
            await pubsub.aclose()


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """
    Clients connect here to receive real-time updates.
    Requires valid session cookie.

    Messages:
      {"type": "alert",      "message": "..."}
      {"type": "ping",       "ts": "..."}
      {"type": "job_update", "job_id": "...", "status": "...", "progress": {...}}
    """
    session_info = await _validate_ws_session(ws)
    if session_info is None:
        await ws.close(code=4001, reason="Unauthorized")
        return

    user_id, role = session_info

    await ws.accept()
    _ws_ip = ws.headers.get("x-forwarded-for", "").split(",")[0].strip() or (ws.client.host if ws.client else "unknown")
    logger.info("WebSocket client connected: %s", _ws_ip)

    tasks = [
        asyncio.create_task(_pubsub_listener(ws, user_id, role)),
        asyncio.create_task(_ping_loop(ws)),
        asyncio.create_task(_ws_receiver(ws)),
    ]
    if role == "admin":
        tasks.append(asyncio.create_task(_log_stream_listener(ws)))
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        # Retrieve exceptions from finished tasks to prevent "never retrieved" warnings
        for t in done:
            with contextlib.suppress(Exception):
                t.result()
        for t in pending:
            t.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await t
    finally:
        logger.info("WebSocket client disconnected: %s", _ws_ip)
