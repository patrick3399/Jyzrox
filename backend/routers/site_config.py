"""Admin API for per-site download configuration — M1/M2.

Endpoints:
    GET    /api/admin/sites              — list all sources with effective params
    GET    /api/admin/sites/{source_id}  — single source details
    PUT    /api/admin/sites/{source_id}  — update overrides
    POST   /api/admin/sites/{source_id}/reset          — reset one field to default
    POST   /api/admin/sites/{source_id}/reset-adaptive  — clear adaptive state
    POST   /api/admin/sites/probe        — probe a URL via gallery-dl --dump-json
    PUT    /api/admin/sites/{source_id}/field-mapping  — save user-confirmed field mappings
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.auth import require_role
from core.site_config import DownloadParams, site_config_service
from db.models import SiteConfig
from plugins.builtin.gallery_dl._sites import get_site_config

router = APIRouter(tags=["admin-sites"])
_admin = require_role("admin")


def _serialize_probe_results(fields: list, mappings: list) -> tuple[list[dict], list[dict]]:
    """Convert ProbeField and FieldMapping dataclasses to dicts."""
    from dataclasses import asdict

    return [asdict(f) for f in fields], [asdict(m) for m in mappings]


class UpdateOverridesRequest(BaseModel):
    download: dict | None = None


class ResetFieldRequest(BaseModel):
    field_path: str


class ProbeRequest(BaseModel):
    url: str


class UpdateFieldMappingRequest(BaseModel):
    field_mapping: dict[str, str | None]


def _build_site_response(
    source_id: str,
    params: DownloadParams,
    row: SiteConfig | None = None,
) -> dict:
    """Build API response for a single source.

    If a DB row is provided, field_mapping and auto_probe are included.
    """
    site = get_site_config(source_id)
    resp: dict = {
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
    if row is not None:
        resp["field_mapping"] = row.overrides.get("field_mapping") if row.overrides else None
        resp["auto_probe"] = row.auto_probe
    return resp


@router.get("")
async def list_sites(_: dict = Depends(_admin)):
    """List all known sources with their effective download params."""
    all_data = await site_config_service.get_all_with_rows()
    return [_build_site_response(sid, params, row) for sid, params, row in all_data]


@router.get("/{source_id}")
async def get_site(source_id: str, _: dict = Depends(_admin)):
    """Get effective download params for a single source."""
    params, row = await site_config_service.get_params_with_row(source_id)
    return _build_site_response(source_id, params, row)


@router.put("/{source_id}")
async def update_site(source_id: str, req: UpdateOverridesRequest, _: dict = Depends(_admin)):
    """Update download overrides for a source."""
    overrides = {}
    if req.download is not None:
        overrides["download"] = req.download

    if not overrides:
        raise HTTPException(status_code=400, detail="No overrides provided")

    try:
        params, row = await site_config_service.update(source_id, overrides)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return _build_site_response(source_id, params, row)


@router.post("/{source_id}/reset")
async def reset_field(source_id: str, req: ResetFieldRequest, _: dict = Depends(_admin)):
    """Reset a specific override field to its _sites.py default."""
    try:
        params, row = await site_config_service.reset(source_id, req.field_path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return _build_site_response(source_id, params, row)


@router.post("/{source_id}/reset-adaptive")
async def reset_adaptive(source_id: str, _: dict = Depends(_admin)):
    """Clear all adaptive auto-tune state for a source."""
    params, row = await site_config_service.reset_adaptive(source_id)
    return _build_site_response(source_id, params, row)


@router.post("/probe")
async def probe_site(req: ProbeRequest, _: dict = Depends(_admin)):
    """Probe a URL via gallery-dl --dump-json. Returns analyzed metadata + suggested mappings."""
    from core.probe import probe_url

    result = await probe_url(req.url)
    if not result.success:
        raise HTTPException(status_code=400, detail=result.error or "Probe failed")

    fields_data, mappings_data = _serialize_probe_results(result.fields, result.suggested_mappings)

    if result.detected_source:
        await site_config_service.save_probe_result(
            result.detected_source,
            {"fields": fields_data, "suggested_mappings": mappings_data},
        )

    return {
        "success": True,
        "detected_source": result.detected_source,
        "raw_metadata": result.raw_metadata,
        "fields": fields_data,
        "suggested_mappings": mappings_data,
    }


@router.put("/{source_id}/field-mapping")
async def update_field_mapping(
    source_id: str,
    req: UpdateFieldMappingRequest,
    _: dict = Depends(_admin),
):
    """Save user-confirmed field mappings to overrides.field_mapping."""
    try:
        params, row = await site_config_service.save_field_mapping(source_id, req.field_mapping)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return _build_site_response(source_id, params, row)
