"""E-Hentai credential flows and verification."""

from __future__ import annotations

import json
import logging

from plugins.models import CredentialFlow, CredentialStatus, FieldDef

logger = logging.getLogger(__name__)


def eh_credential_flows() -> list[CredentialFlow]:
    """Return the supported credential flows for E-Hentai."""
    return [
        CredentialFlow(
            flow_type="fields",
            fields=[
                FieldDef(name="ipb_member_id", field_type="text", label="ipb_member_id", required=True, placeholder="12345"),
                FieldDef(name="ipb_pass_hash", field_type="password", label="ipb_pass_hash", required=True),
                FieldDef(name="sk", field_type="password", label="sk", required=False),
                FieldDef(name="igneous", field_type="password", label="igneous (ExHentai)", required=False),
            ],
            verify_endpoint="/api/settings/credentials/ehentai/cookies-check",
        ),
        CredentialFlow(
            flow_type="login",
            login_endpoint="/api/settings/credentials/ehentai/login",
            verify_endpoint="/api/settings/credentials/ehentai/cookies-check",
        ),
    ]


async def verify_eh_credential(credentials: dict) -> CredentialStatus:
    """Verify E-Hentai cookies by testing access against EhClient."""
    from services.eh_client import EhClient

    cookies = credentials
    if isinstance(credentials, str):
        try:
            cookies = json.loads(credentials)
        except (json.JSONDecodeError, TypeError):
            return CredentialStatus(valid=False, error="Malformed credentials JSON")

    if not cookies.get("ipb_member_id") or not cookies.get("ipb_pass_hash"):
        return CredentialStatus(valid=False, error="Missing required cookies")

    try:
        use_ex = bool(cookies.get("igneous"))
        async with EhClient(cookies=cookies, use_ex=use_ex) as client:
            valid = await client.check_cookies()
            if valid:
                account = await client.get_account_info()
                return CredentialStatus(
                    valid=True,
                    username=account.get("username"),
                )
            return CredentialStatus(valid=False, error="Cookie check failed")
    except Exception as exc:
        logger.warning("[eh_credentials] verify failed: %s", exc)
        return CredentialStatus(valid=False, error=str(exc))
