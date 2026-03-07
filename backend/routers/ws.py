"""WebSocket endpoint — real-time download progress and system alerts."""

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from services.cache import clear_system_alerts, get_system_alerts

logger = logging.getLogger(__name__)
router = APIRouter(tags=["websocket"])


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """
    Clients connect here to receive real-time updates.
    Currently uses 2s polling; Phase 3+ can upgrade to Redis pub/sub.

    Messages:
      {"type": "alert",    "message": "..."}
      {"type": "ping",     "ts": "..."}
    """
    await ws.accept()
    logger.info("WebSocket client connected: %s", ws.client)

    try:
        while True:
            # Flush any queued system alerts
            alerts = await get_system_alerts()
            if alerts:
                for msg in alerts:
                    await ws.send_json({"type": "alert", "message": msg})
                await clear_system_alerts()

            # Keepalive ping
            import datetime
            await ws.send_json({"type": "ping", "ts": datetime.datetime.utcnow().isoformat()})

            await asyncio.sleep(2)

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected: %s", ws.client)
    except Exception as exc:
        logger.error("WebSocket error: %s", exc)
