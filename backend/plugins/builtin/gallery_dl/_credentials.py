"""Generic cookie credential flows for gallery-dl."""

import json

from plugins.models import CredentialFlow, CredentialStatus, FieldDef

def parse_cookie_input(raw: str) -> dict[str, str]:
    """Parse cookie input in multiple formats: JSON, per-line key=val, browser semicolon format, or single key=val."""
    raw = raw.strip()
    if not raw:
        return {}

    # Try JSON first
    if raw.startswith("{"):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return {str(k): str(v) for k, v in parsed.items()}
        except json.JSONDecodeError, TypeError:
            pass

    def _split_pairs(text: str, delimiter: str) -> dict[str, str]:
        result = {}
        for part in text.split(delimiter):
            part = part.strip()
            if not part:
                continue
            eq = part.find("=")
            if eq > 0:
                result[part[:eq].strip()] = part[eq + 1:].strip()
        return result

    # Per-line format (has newlines)
    if "\n" in raw:
        return _split_pairs(raw, "\n")

    # Semicolon-separated (browser format)
    if ";" in raw:
        return _split_pairs(raw, ";")

    # Single key=value
    eq = raw.find("=")
    if eq > 0:
        return {raw[:eq].strip(): raw[eq + 1:].strip()}

    return {}

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
