"""Pixiv credential flows and verification."""

import logging

from plugins.models import CredentialFlow, CredentialStatus, FieldDef, OAuthConfig

logger = logging.getLogger(__name__)

def pixiv_credential_flows() -> list[CredentialFlow]:
    """Return the supported credential flows for Pixiv."""
    return [
        CredentialFlow(
            flow_type="fields",
            fields=[
                FieldDef(
                    name="refresh_token",
                    field_type="password",
                    label="Refresh Token",
                    required=True,
                ),
            ],
            verify_endpoint="/api/settings/credentials/pixiv",
        ),
        CredentialFlow(
            flow_type="oauth",
            oauth_config=OAuthConfig(
                auth_url_endpoint="/api/settings/credentials/pixiv/oauth-url",
                callback_endpoint="/api/settings/credentials/pixiv/oauth-callback",
                display_name="Pixiv OAuth Login",
            ),
        ),
        CredentialFlow(
            flow_type="login",
            login_endpoint="/api/settings/credentials/pixiv/cookie",
            fields=[
                FieldDef(
                    name="phpsessid",
                    field_type="password",
                    label="PHPSESSID Cookie",
                    required=True,
                    placeholder="Paste your PHPSESSID from pixiv.net",
                ),
            ],
        ),
    ]

async def verify_pixiv_credential(credentials: dict) -> CredentialStatus:
    """Verify a Pixiv refresh token."""
    import asyncio

    refresh_token = credentials.get("refresh_token", "")
    if isinstance(credentials, str):
        refresh_token = credentials

    if not refresh_token:
        return CredentialStatus(valid=False, error="No refresh token provided")

    try:
        import pixivpy3

        api = pixivpy3.AppPixivAPI()
        await asyncio.to_thread(api.auth, refresh_token=refresh_token)
        detail = await asyncio.to_thread(api.user_detail, api.user_id)
        username = detail.user.name
        return CredentialStatus(valid=True, username=username)
    except (ImportError, AttributeError, ValueError, OSError) as exc:
        return CredentialStatus(valid=False, error=f"Pixiv auth failed: {exc}")
    except Exception as exc:
        return CredentialStatus(valid=False, error=str(exc))
