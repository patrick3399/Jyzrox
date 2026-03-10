"""Plugin management API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

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
        credential_provider = plugin_registry.get_credential_provider(meta.source_id)
        credential_flows = []
        if credential_provider:
            credential_flows = [f.model_dump() for f in credential_provider.credential_flows()]
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
                "credential_flows": credential_flows,
                "enabled": True,  # TODO: read from plugin_config table
            }
        )

    return {"plugins": plugins}
