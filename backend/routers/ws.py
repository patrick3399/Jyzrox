"""WebSocket endpoint — real-time download progress and system alerts."""

import asyncio
import datetime
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from core.redis_client import get_redis
from services.cache import clear_system_alerts, get_system_alerts

logger = logging.getLogger(__name__)
router = APIRouter(tags=["websocket"])


async def _validate_ws_session(ws: WebSocket) -> bool:
    """Validate session cookie from WebSocket handshake."""
    vault_session = ws.cookies.get("vault_session")
    if not vault_session:
        return False
    try:
        user_id_str, token = vault_session.split(":", 1)
        session_data = await get_redis().get(f"session:{user_id_str}:{token}")
        return session_data is not None
    except (ValueError, Exception):
        return False


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """
    Clients connect here to receive real-time updates.
    Requires valid session cookie.

    Messages:
      {"type": "alert",    "message": "..."}
      {"type": "ping",     "ts": "..."}
    """
    if not await _validate_ws_session(ws):
        await ws.close(code=4001, reason="Unauthorized")
        return

    await ws.accept()
    logger.info("WebSocket client connected: %s", ws.client)

    try:
        while True:
            alerts = await get_system_alerts()
            if alerts:
                for msg in alerts:
                    await ws.send_json({"type": "alert", "message": msg})
                await clear_system_alerts()

            await ws.send_json({"type": "ping", "ts": datetime.datetime.utcnow().isoformat()})
            await asyncio.sleep(2)

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected: %s", ws.client)
    except Exception as exc:
        logger.error("WebSocket error: %s", exc)
