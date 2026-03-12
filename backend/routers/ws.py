"""WebSocket endpoint — real-time download progress and system alerts."""

import asyncio
import contextlib
import datetime
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from core.redis_client import get_pubsub, get_redis
from services.cache import clear_system_alerts, get_system_alerts

logger = logging.getLogger(__name__)
router = APIRouter(tags=["websocket"])


async def _validate_ws_session(ws: WebSocket) -> str | None:
    """Validate session cookie from WebSocket handshake. Returns user_id str or None."""
    vault_session = ws.cookies.get("vault_session")
    if not vault_session:
        return None
    try:
        user_id_str, token = vault_session.split(":", 1)
        session_data = await get_redis().get(f"session:{user_id_str}:{token}")
        return user_id_str if session_data is not None else None
    except (ValueError, ConnectionError, OSError) as exc:
        logger.warning("WS session validation failed: %s", exc)
        return None


async def _pubsub_listener(ws: WebSocket) -> None:
    """Subscribe to download:events and forward messages to the WebSocket client."""
    pubsub = get_pubsub()
    try:
        await pubsub.subscribe("download:events")
        async for message in pubsub.listen():
            if message["type"] == "message":
                data = message["data"]
                if isinstance(data, bytes):
                    data = data.decode()
                await ws.send_text(data)
    except (WebSocketDisconnect, asyncio.CancelledError):
        raise
    except Exception as exc:
        logger.warning("_pubsub_listener error: %s", exc)
        raise
    finally:
        with contextlib.suppress(Exception):
            await pubsub.unsubscribe("download:events")
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

            await ws.send_json({"type": "ping", "ts": datetime.datetime.now(datetime.timezone.utc).isoformat()})
            await asyncio.sleep(2)
    except (WebSocketDisconnect, asyncio.CancelledError):
        raise
    except (ConnectionError, RuntimeError) as exc:
        logger.error("_ping_loop error: %s", exc)
        raise


async def _ws_receiver(ws: WebSocket) -> None:
    """Receive messages from the client (detect disconnect)."""
    try:
        while True:
            await ws.receive()
    except (WebSocketDisconnect, asyncio.CancelledError, RuntimeError):
        raise


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
    user_id = await _validate_ws_session(ws)
    if user_id is None:
        await ws.close(code=4001, reason="Unauthorized")
        return

    await ws.accept()
    logger.info("WebSocket client connected: %s", ws.client)

    tasks = [
        asyncio.create_task(_pubsub_listener(ws)),
        asyncio.create_task(_ping_loop(ws)),
        asyncio.create_task(_ws_receiver(ws)),
    ]
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
        logger.info("WebSocket client disconnected: %s", ws.client)
