"""Generic cookie credential flows for gallery-dl."""

from __future__ import annotations

from plugins.models import CredentialFlow, CredentialStatus, FieldDef


def gallery_dl_credential_flows() -> list[CredentialFlow]:
    """Return the generic cookie credential flow.

    gallery-dl handles many sites. Each site can have its own cookies
    saved via the generic cookie endpoint.
    """
    return [
        CredentialFlow(
            flow_type="fields",
            fields=[
                FieldDef(
                    name="source",
                    field_type="text",
                    label="Site Name",
                    required=True,
                    placeholder="twitter, instagram, danbooru...",
                ),
                FieldDef(
                    name="cookies",
                    field_type="textarea",
                    label="Cookies (JSON)",
                    required=True,
                    placeholder='{"cookie_name": "cookie_value"}',
                ),
            ],
            verify_endpoint=None,
        ),
    ]


async def verify_gallery_dl_credential(credentials: dict) -> CredentialStatus:
    """Generic credentials cannot be verified — accept as-is."""
    if not credentials:
        return CredentialStatus(valid=False, error="No credentials provided")
    return CredentialStatus(valid=True)
