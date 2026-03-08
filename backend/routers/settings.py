"""Credential management and system settings."""

import base64
import hashlib
import json
import logging
import secrets
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text

from core.auth import require_auth
from core.config import settings as app_settings
from core.database import async_session
from services.cache import get_system_alerts, push_system_alert
from services.credential import get_credential, set_credential
from services.eh_client import EhClient

logger = logging.getLogger(__name__)
router = APIRouter(tags=["settings"])


# ── Models ───────────────────────────────────────────────────────────


class EhCookieRequest(BaseModel):
    ipb_member_id: str
    ipb_pass_hash: str
    sk: str
    igneous: str | None = None


class EhLoginRequest(BaseModel):
    username: str
    password: str


class PixivTokenRequest(BaseModel):
    refresh_token: str


class PixivOAuthCallbackRequest(BaseModel):
    code: str
    code_verifier: str


class RateLimitPatch(BaseModel):
    enabled: bool | None = None


# ── Credentials ──────────────────────────────────────────────────────


@router.get("/credentials")
async def list_credentials(_: dict = Depends(require_auth)):
    """Which credential sources are configured (values never exposed)."""
    sources = ["ehentai", "pixiv"]
    return {src: {"configured": (await get_credential(src)) is not None} for src in sources}


@router.post("/credentials/ehentai/login")
async def eh_login_with_password(
    req: EhLoginRequest,
    _: dict = Depends(require_auth),
):
    """Login to E-Hentai with username/password to auto-obtain cookies (EhViewer-style)."""
    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        resp = await client.post(
            "https://forums.e-hentai.org/index.php?act=Login&CODE=01",
            data={
                "UserName": req.username,
                "PassWord": req.password,
                "submit": "Log me in",
                "CookieDate": "1",
                "temporary_https": "off",
            },
            headers={"Referer": "https://forums.e-hentai.org/index.php?act=Login&CODE=00"},
        )

    ipb_member_id = resp.cookies.get("ipb_member_id")
    ipb_pass_hash = resp.cookies.get("ipb_pass_hash")
    if not ipb_member_id or not ipb_pass_hash:
        raise HTTPException(status_code=400, detail="Login failed: incorrect username or password")

    # Fetch sk cookie from main EH page
    async with httpx.AsyncClient(
        cookies={"ipb_member_id": ipb_member_id, "ipb_pass_hash": ipb_pass_hash},
        follow_redirects=True,
        timeout=15,
    ) as client:
        resp2 = await client.get("https://e-hentai.org/")
    sk = resp2.cookies.get("sk", "")

    cookies = {"ipb_member_id": ipb_member_id, "ipb_pass_hash": ipb_pass_hash, "sk": sk}

    # Try to obtain igneous cookie for ExHentai access
    igneous = None
    try:
        async with httpx.AsyncClient(
            cookies=cookies,
            follow_redirects=True,
            timeout=15,
        ) as ex_client:
            ex_resp = await ex_client.get("https://exhentai.org/")
            igneous = ex_resp.cookies.get("igneous")
            if not igneous:
                # Check if it was set on the initial response
                for h_name, h_val in ex_resp.headers.multi_items():
                    if h_name.lower() == "set-cookie" and "igneous" in h_val:
                        import re as _re

                        m = _re.search(r"igneous=([^;]+)", h_val)
                        if m:
                            igneous = m.group(1)
                            break
    except (httpx.HTTPError, httpx.TimeoutException, OSError) as exc:
        logger.warning("ExHentai igneous cookie fetch failed: %s", exc)

    if igneous:
        cookies["igneous"] = igneous

    use_ex = bool(igneous)
    async with EhClient(cookies=cookies, use_ex=use_ex) as client:
        if not await client.check_cookies():
            raise HTTPException(status_code=400, detail="Login succeeded but cookies are invalid")
        account = await client.get_account_info()

    await set_credential("ehentai", json.dumps(cookies), "cookie")
    return {"status": "ok", "account": account, "use_ex": use_ex}


@router.post("/credentials/ehentai")
async def set_eh_credentials(
    req: EhCookieRequest,
    _: dict = Depends(require_auth),
):
    """Save E-Hentai cookies after verifying them."""
    cookies = {
        "ipb_member_id": req.ipb_member_id,
        "ipb_pass_hash": req.ipb_pass_hash,
        "sk": req.sk,
    }
    if req.igneous:
        cookies["igneous"] = req.igneous
    use_ex = bool(req.igneous)
    async with EhClient(cookies=cookies, use_ex=use_ex) as client:
        if not await client.check_cookies():
            raise HTTPException(status_code=400, detail="EH cookies are invalid")
        account = await client.get_account_info()

    await set_credential("ehentai", json.dumps(cookies), "cookie")
    return {"status": "ok", "account": account}


@router.post("/credentials/pixiv")
async def set_pixiv_credentials(
    req: PixivTokenRequest,
    _: dict = Depends(require_auth),
):
    """Save Pixiv refresh_token after verifying it via pixivpy3."""
    try:
        import pixivpy3

        api = pixivpy3.AppPixivAPI()
        api.auth(refresh_token=req.refresh_token)
        detail = api.user_detail(api.user_id)
        username = detail.user.name
    except (ImportError, AttributeError, ValueError, OSError) as exc:
        logger.error("Pixiv auth failed: %s", exc)
        raise HTTPException(status_code=400, detail=f"Pixiv auth failed: {exc}")

    await set_credential("pixiv", req.refresh_token, "oauth_token")
    return {"status": "ok", "username": username}


@router.get("/credentials/pixiv/oauth-url")
async def get_pixiv_oauth_url(_: dict = Depends(require_auth)):
    """Generate PKCE verifier and authorization URL for Pixiv."""
    code_verifier = secrets.token_urlsafe(32)
    code_challenge_bytes = hashlib.sha256(code_verifier.encode("utf-8")).digest()
    code_challenge = base64.urlsafe_b64encode(code_challenge_bytes).decode("utf-8").rstrip("=")

    client_id = "MOBrBDS8blbauoSck0ZfDbtuzpyT"
    auth_url = (
        f"https://app-api.pixiv.net/web/v1/login"
        f"?code_challenge={code_challenge}"
        f"&code_challenge_method=S256"
        f"&client={client_id}"
    )
    return {"url": auth_url, "code_verifier": code_verifier}


@router.post("/credentials/pixiv/oauth-callback")
async def pixiv_oauth_callback(
    req: PixivOAuthCallbackRequest,
    _: dict = Depends(require_auth),
):
    """Exchange authorization code for refresh token."""
    client_id = "MOBrBDS8blbauoSck0ZfDbtuzpyT"
    client_secret = "lsACyCD94FhDUtGTXi3QzcFE2uU1hqtDaKeqrdwj"

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
        headers = {
            "User-Agent": "PixivAndroidApp/5.0.234 (Android 11; Pixel 5)",
            "App-OS-Version": "11",
            "App-OS": "android",
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post("https://oauth.secure.pixiv.net/auth/token", data=data, headers=headers)
            resp.raise_for_status()
            token_data = resp.json()
            refresh_token = token_data.get("refresh_token")
            username = token_data.get("user", {}).get("name", "Unknown")

            if not refresh_token:
                raise ValueError("No refresh token in response")

    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Pixiv OAuth failed: {exc}")

    await set_credential("pixiv", refresh_token, "oauth_token")
    return {"status": "ok", "username": username}


# ── ExHentai cookie check ─────────────────────────────────────────────


@router.post("/credentials/ehentai/cookies-check")
async def eh_cookies_check(_: dict = Depends(require_auth)):
    """Verify whether stored cookies can access ExHentai."""
    cred_json = await get_credential("ehentai")
    if not cred_json:
        raise HTTPException(status_code=404, detail="EH credentials not configured")

    cookies = json.loads(cred_json)
    has_igneous = bool(cookies.get("igneous"))

    # Test ExH access
    ex_ok = False
    if has_igneous:
        try:
            async with EhClient(cookies=cookies, use_ex=True) as client:
                ex_ok = await client.check_cookies()
        except (httpx.HTTPError, httpx.TimeoutException, OSError) as exc:
            logger.warning("ExH cookie check failed: %s", exc)
            ex_ok = False

    # Test EH access
    eh_ok = False
    try:
        async with EhClient(cookies=cookies, use_ex=False) as client:
            eh_ok = await client.check_cookies()
    except (httpx.HTTPError, httpx.TimeoutException, OSError) as exc:
        logger.warning("EH cookie check failed: %s", exc)
        eh_ok = False

    return {
        "eh_valid": eh_ok,
        "ex_valid": ex_ok,
        "has_igneous": has_igneous,
    }


# ── Account info ─────────────────────────────────────────────────────


@router.get("/eh/account")
async def eh_account_info(_: dict = Depends(require_auth)):
    """Get live E-Hentai account status and GP balance."""
    cred_json = await get_credential("ehentai")
    if not cred_json:
        raise HTTPException(status_code=404, detail="EH credentials not configured")

    async with EhClient(cookies=json.loads(cred_json)) as client:
        if not await client.check_cookies():
            await push_system_alert("E-Hentai cookie invalid or expired")
            raise HTTPException(status_code=401, detail="EH cookie invalid")
        info = await client.get_account_info()

    return {"valid": True, **info}


# ── Rate Limiting ────────────────────────────────────────────────


@router.get("/rate-limit")
async def get_rate_limit_settings(_: dict = Depends(require_auth)):
    """Get current rate limiting status."""
    return {
        "enabled": app_settings.rate_limit_enabled,
        "login_max": app_settings.rate_limit_login,
        "window": app_settings.rate_limit_window,
    }


@router.patch("/rate-limit")
async def patch_rate_limit_settings(
    req: RateLimitPatch,
    _: dict = Depends(require_auth),
):
    """Toggle rate limiting on/off at runtime."""
    if req.enabled is not None:
        app_settings.rate_limit_enabled = req.enabled
    return {
        "enabled": app_settings.rate_limit_enabled,
    }


# ── Alerts ───────────────────────────────────────────────────────────


@router.get("/alerts")
async def get_alerts(_: dict = Depends(require_auth)):
    """Return queued system alerts (cookie expiry, etc.)."""
    return {"alerts": await get_system_alerts()}


# ── API Tokens ────────────────────────────────────────────────────────


class CreateTokenRequest(BaseModel):
    name: str
    expires_days: int | None = None  # None = never expires


@router.get("/tokens")
async def list_tokens(auth: dict = Depends(require_auth)):
    """List all API tokens for the current user."""
    async with async_session() as session:
        rows = await session.execute(
            text("""
                SELECT id, name, token_hash, created_at, last_used_at, expires_at
                FROM api_tokens
                WHERE user_id = :uid
                ORDER BY created_at DESC
            """),
            {"uid": auth["user_id"]},
        )
    tokens = []
    for r in rows:
        tokens.append(
            {
                "id": str(r.id),
                "name": r.name,
                "token_prefix": r.token_hash[:8],
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "last_used_at": r.last_used_at.isoformat() if r.last_used_at else None,
                "expires_at": r.expires_at.isoformat() if r.expires_at else None,
            }
        )
    return {"tokens": tokens}


@router.post("/tokens")
async def create_token(
    req: CreateTokenRequest,
    auth: dict = Depends(require_auth),
):
    """Create a new API token."""
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

    expires_at = None
    if req.expires_days and req.expires_days > 0:
        from datetime import timedelta

        expires_at = datetime.now(UTC) + timedelta(days=req.expires_days)

    async with async_session() as session:
        result = await session.execute(
            text("""
                INSERT INTO api_tokens (user_id, name, token_hash, token_plain, expires_at)
                VALUES (:uid, :name, :hash, NULL, :exp)
                RETURNING id, created_at
            """),
            {
                "uid": auth["user_id"],
                "name": req.name.strip(),
                "hash": token_hash,
                "exp": expires_at,
            },
        )
        row = result.fetchone()
        await session.commit()

    return {
        "id": str(row.id),
        "name": req.name.strip(),
        "token": raw_token,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "expires_at": expires_at.isoformat() if expires_at else None,
    }


@router.delete("/tokens/{token_id}")
async def delete_token(
    token_id: str,
    auth: dict = Depends(require_auth),
):
    """Revoke/delete an API token."""
    async with async_session() as session:
        result = await session.execute(
            text("DELETE FROM api_tokens WHERE id = :id AND user_id = :uid RETURNING id"),
            {"id": token_id, "uid": auth["user_id"]},
        )
        deleted = result.fetchone()
        await session.commit()

    if not deleted:
        raise HTTPException(status_code=404, detail="Token not found")
    return {"status": "ok"}


@router.patch("/tokens/{token_id}")
async def update_token(
    token_id: str,
    name: str = Query(default=None),
    auth: dict = Depends(require_auth),
):
    """Update token name."""
    if not name or not name.strip():
        raise HTTPException(status_code=400, detail="Name is required")

    async with async_session() as session:
        result = await session.execute(
            text("UPDATE api_tokens SET name = :name WHERE id = :id AND user_id = :uid RETURNING id"),
            {"name": name.strip(), "id": token_id, "uid": auth["user_id"]},
        )
        updated = result.fetchone()
        await session.commit()

    if not updated:
        raise HTTPException(status_code=404, detail="Token not found")
    return {"status": "ok"}
