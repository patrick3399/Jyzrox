"""Settings: Pixiv credentials."""

import base64
import hashlib
import logging
import secrets
import urllib.parse

import httpx
from fastapi import APIRouter, Depends, HTTPException

from core.auth import require_role
from core.client_identity import browser_headers, pixiv_app_headers
from core.config import settings as app_settings
from services.browser_http import browser_client
from services.credential import set_credential
from services.settings_schemas import (
    PixivCookieRequest,
    PixivOAuthCallbackRequest,
    PixivTokenRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter()

_admin = require_role("admin")
_member = require_role("member")


@router.post("/credentials/pixiv")
async def set_pixiv_credentials(
    req: PixivTokenRequest,
    _: dict = Depends(_admin),
):
    """Save Pixiv refresh_token after verifying it via pixivpy3."""
    try:
        import asyncio as _asyncio

        from services.pixiv_client import new_app_api

        api = new_app_api()
        await _asyncio.to_thread(api.auth, refresh_token=req.refresh_token)
        detail = await _asyncio.to_thread(api.user_detail, api.user_id)
        username = detail.user.name
    except (ImportError, AttributeError, ValueError, OSError) as exc:
        logger.error("Pixiv auth failed: %s", exc)
        raise HTTPException(status_code=400, detail=f"Pixiv auth failed: {exc}")

    await set_credential("pixiv", req.refresh_token, "oauth_token", account=req.account)
    return {"status": "ok", "username": username}


@router.get("/credentials/pixiv/oauth-url")
async def get_pixiv_oauth_url(_: dict = Depends(_admin)):
    """Generate PKCE verifier and authorization URL for Pixiv."""
    code_verifier = secrets.token_urlsafe(32)
    code_challenge_bytes = hashlib.sha256(code_verifier.encode("utf-8")).digest()
    code_challenge = base64.urlsafe_b64encode(code_challenge_bytes).decode("utf-8").rstrip("=")

    client_id = app_settings.pixiv_client_id
    redirect_uri = "https://app-api.pixiv.net/web/v1/users/auth/pixiv/callback"
    auth_url = (
        f"https://accounts.pixiv.net/login"
        f"?client_id={client_id}"
        f"&redirect_uri={urllib.parse.quote(redirect_uri, safe='')}"
        f"&response_type=code"
        f"&code_challenge={code_challenge}"
        f"&code_challenge_method=S256"
    )
    return {"url": auth_url, "code_verifier": code_verifier}


@router.post("/credentials/pixiv/oauth-callback")
async def pixiv_oauth_callback(
    req: PixivOAuthCallbackRequest,
    _: dict = Depends(_admin),
):
    """Exchange authorization code for refresh token."""
    client_id = app_settings.pixiv_client_id
    client_secret = app_settings.pixiv_client_secret

    # Extract code from URL if user pasted the full URL
    code = req.code
    if "code=" in code:
        import urllib.parse

        parsed = urllib.parse.urlparse(code)
        qs = urllib.parse.parse_qs(parsed.query)
        if "code" in qs:
            code = qs["code"][0]

    try:
        data = {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "code_verifier": req.code_verifier,
            "grant_type": "authorization_code",
            "redirect_uri": "https://app-api.pixiv.net/web/v1/users/auth/pixiv/callback",
            "include_policy": "true",
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://oauth.secure.pixiv.net/auth/token", data=data, headers=pixiv_app_headers()
            )
            resp.raise_for_status()
            token_data = resp.json()
            refresh_token = token_data.get("refresh_token")
            username = token_data.get("user", {}).get("name", "Unknown")

            if not refresh_token:
                raise ValueError("No refresh token in response")

    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Pixiv OAuth failed: {exc}")

    await set_credential("pixiv", refresh_token, "oauth_token", account=req.account)
    return {"status": "ok", "username": username}


@router.post("/credentials/pixiv/cookie")
async def set_pixiv_cookie_credentials(
    req: PixivCookieRequest,
    _: dict = Depends(_admin),
):
    """
    Simulate Pixiv OAuth flow using a session cookie (PHPSESSID).
    Catches the 302 redirect to grab the code and exchange it.
    """
    code_verifier = secrets.token_urlsafe(32)
    code_challenge_bytes = hashlib.sha256(code_verifier.encode("utf-8")).digest()
    code_challenge = base64.urlsafe_b64encode(code_challenge_bytes).decode("utf-8").rstrip("=")

    client_id = app_settings.pixiv_client_id
    redirect_uri = "https://app-api.pixiv.net/web/v1/users/auth/pixiv/callback"
    auth_url = (
        f"https://accounts.pixiv.net/login"
        f"?client_id={client_id}"
        f"&redirect_uri={urllib.parse.quote(redirect_uri, safe='')}"
        f"&response_type=code"
        f"&code_challenge={code_challenge}"
        f"&code_challenge_method=S256"
    )

    try:
        # Step 1: Hit the OAuth URL with the provided PHPSESSID cookie
        # follow_redirects=False is crucial here to capture the 302 response
        cookies = {"PHPSESSID": req.phpsessid}
        async with browser_client(follow_redirects=False) as client:
            resp = await client.get(auth_url, cookies=cookies, headers=browser_headers("document", site="none"))

            # The expected success response is a 302 redirect back to the app-api.pixiv.net URL
            if resp.status_code != 302:
                raise ValueError("Invalid session cookie or user not logged in. (Expected 302 redirect)")

            location = resp.headers.get("Location")
            if not location or "code=" not in location:
                raise ValueError("No authorization code found in redirect URL")

            # Extract code from location
            parsed = urllib.parse.urlparse(location)
            qs = urllib.parse.parse_qs(parsed.query)
            if "code" not in qs:
                raise ValueError("Failed to extract code from callback URL")

            code = qs["code"][0]

        # Step 2: Exchange the code for a refresh_token (same as OAuth callback)
        client_secret = app_settings.pixiv_client_secret
        data = {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "code_verifier": code_verifier,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
            "include_policy": "true",
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://oauth.secure.pixiv.net/auth/token", data=data, headers=pixiv_app_headers()
            )
            resp.raise_for_status()
            token_data = resp.json()
            refresh_token = token_data.get("refresh_token")
            username = token_data.get("user", {}).get("name", "Unknown")

            if not refresh_token:
                raise ValueError("No refresh token in response")

    except Exception as exc:
        logger.error("Pixiv cookie auth failed: %s", exc)
        raise HTTPException(status_code=400, detail=f"Pixiv cookie auth failed: {exc}")

    # Step 3: Save the credential
    await set_credential("pixiv", refresh_token, "oauth_token", account=req.account)
    return {"status": "ok", "username": username}


# ── SauceNAO ─────────────────────────────────────────────────────────
