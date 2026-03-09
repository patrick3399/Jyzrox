"""Plugin management API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from core.auth import require_auth
from plugins.registry import plugin_registry

router = APIRouter(tags=["plugins"])


@router.get("/")
async def list_plugins(_: dict = Depends(require_auth)):
    """List all registered plugins with their metadata and credential status."""
    from services.credential import list_credentials

    configured_creds = await list_credentials()
    configured_sources = {c["source"] for c in configured_creds}

    plugins: list[dict] = []
    seen: set[str] = set()

    for meta in plugin_registry.list_plugins():
        if meta.source_id in seen:
            continue
        seen.add(meta.source_id)

        browser = plugin_registry.get_browser(meta.source_id)
        plugins.append(
            {
                "name": meta.name,
                "source_id": meta.source_id,
                "version": meta.version,
                "url_patterns": meta.url_patterns,
                "credential_schema": [f.model_dump() for f in meta.credential_schema],
                "has_browse": browser is not None,
                "browse_schema": browser.browse_schema().model_dump() if browser else None,
                "credential_configured": meta.source_id in configured_sources,
                "enabled": True,  # TODO: read from plugin_config table
            }
        )

    return {"plugins": plugins}


@router.get("/{source_id}/browse")
async def plugin_browse(
    source_id: str,
    _: dict = Depends(require_auth),
):
    """Proxy search to a BrowsePlugin (source-specific endpoints are preferred)."""
    browser = plugin_registry.get_browser(source_id)
    if not browser:
        raise HTTPException(status_code=404, detail=f"No browse plugin for {source_id}")
    # Source-specific routers (e.g. /api/eh/search) handle the actual browsing.
    raise HTTPException(
        status_code=501,
        detail="Use source-specific browse endpoints (e.g. /api/eh/search)",
    )
