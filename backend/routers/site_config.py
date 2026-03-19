"""Admin API for per-site download configuration — M1.

Endpoints:
    GET    /api/admin/sites              — list all sources with effective params
    GET    /api/admin/sites/{source_id}  — single source details
    PUT    /api/admin/sites/{source_id}  — update overrides
    POST   /api/admin/sites/{source_id}/reset          — reset one field to default
    POST   /api/admin/sites/{source_id}/reset-adaptive  — clear adaptive state
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.auth import require_role
from core.site_config import DownloadParams, site_config_service
from plugins.builtin.gallery_dl._sites import get_site_config

router = APIRouter(tags=["admin-sites"])
_admin = require_role("admin")


class UpdateOverridesRequest(BaseModel):
    download: dict | None = None


class ResetFieldRequest(BaseModel):
    field_path: str


def _build_site_response(source_id: str, params: DownloadParams) -> dict:
    """Build API response for a single source."""
    site = get_site_config(source_id)
    return {
        "source_id": source_id,
        "name": site.name,
        "domain": site.domain,
        "category": site.category,
        "download": {
            "retries": params.retries,
            "http_timeout": params.http_timeout,
            "sleep_request": params.sleep_request,
            "concurrency": params.concurrency,
            "inactivity_timeout": params.inactivity_timeout,
        },
    }


@router.get("")
async def list_sites(_: dict = Depends(_admin)):
    """List all known sources with their effective download params."""
    all_params = await site_config_service.get_all_download_params()
    return [_build_site_response(sid, params) for sid, params in all_params.items()]


@router.get("/{source_id}")
async def get_site(source_id: str, _: dict = Depends(_admin)):
    """Get effective download params for a single source."""
    params = await site_config_service.get_effective_download_params(source_id)
    return _build_site_response(source_id, params)


@router.put("/{source_id}")
async def update_site(source_id: str, req: UpdateOverridesRequest, _: dict = Depends(_admin)):
    """Update download overrides for a source."""
    overrides = {}
    if req.download is not None:
        overrides["download"] = req.download

    if not overrides:
        raise HTTPException(status_code=400, detail="No overrides provided")

    try:
        params = await site_config_service.update(source_id, overrides)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return _build_site_response(source_id, params)


@router.post("/{source_id}/reset")
async def reset_field(source_id: str, req: ResetFieldRequest, _: dict = Depends(_admin)):
    """Reset a specific override field to its _sites.py default."""
    try:
        params = await site_config_service.reset(source_id, req.field_path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return _build_site_response(source_id, params)


@router.post("/{source_id}/reset-adaptive")
async def reset_adaptive(source_id: str, _: dict = Depends(_admin)):
    """Clear all adaptive auto-tune state for a source."""
    params = await site_config_service.reset_adaptive(source_id)
    return _build_site_response(source_id, params)
