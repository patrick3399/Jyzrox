"""External API endpoints for third-party integrations."""

import hashlib
import shutil

import psutil
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy import text

from core.config import settings
from core.database import async_session

router = APIRouter(tags=["external"])

async def verify_api_token(x_api_token: str = Header(...)):
    if not x_api_token:
        raise HTTPException(status_code=401, detail="Missing X-API-Token header")

    token_hash = hashlib.sha256(x_api_token.encode()).hexdigest()
    async with async_session() as session:
        result = await session.execute(
            text("SELECT id, user_id FROM api_tokens WHERE token_hash = :th AND (expires_at IS NULL OR expires_at > now())"),
            {"th": token_hash},
        )
        token = result.fetchone()

    if not token:
        raise HTTPException(status_code=401, detail="Invalid or expired API token")

    return {"user_id": token.user_id, "token_id": token.id}


@router.get("/status")
async def system_status(token_data: dict = Depends(verify_api_token)):
    """Returns basic system status and stats for external dashboards (e.g. Homepage)."""
    
    async with async_session() as session:
        counts = await session.execute(text("""
            SELECT 
                (SELECT COUNT(*) FROM galleries) as gallery_count,
                (SELECT COUNT(*) FROM images) as image_count,
                (SELECT COUNT(*) FROM tags) as tag_count
        """))
        stats = counts.fetchone()

    try:
        usage = shutil.disk_usage(settings.data_gallery_path)
        disk_total = usage.total
        disk_free = usage.free
    except OSError:
        disk_total = 0
        disk_free = 0

    return {
        "status": "online",
        "version": "2.0.0",
        "stats": {
            "galleries": stats.gallery_count,
            "images": stats.image_count,
            "tags": stats.tag_count
        },
        "system": {
            "cpu_percent": psutil.cpu_percent(),
            "memory_percent": psutil.virtual_memory().percent,
            "disk_free_bytes": disk_free,
            "disk_total_bytes": disk_total
        }
    }
