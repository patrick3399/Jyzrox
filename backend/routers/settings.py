"""Credential management and system settings."""

import base64
import hashlib
import json
import logging
import secrets
import urllib.parse
from datetime import UTC, datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, text

from core.auth import require_auth, require_role
from core.config import settings as app_settings
from core.database import async_session
from core.redis_client import get_redis, is_rate_limit_boosted
from db.models import Credential
from services.cache import get_system_alerts, push_system_alert
from services.credential import get_credential, list_credentials, set_credential
from services.eh_client import EhClient

logger = logging.getLogger(__name__)
router = APIRouter(tags=["settings"])

_admin = require_role("admin")
_member = require_role("member")


# ── Models ───────────────────────────────────────────────────────────


class EhCookieRequest(BaseModel):
    ipb_member_id: str
    ipb_pass_hash: str
    sk: str | None = None
    igneous: str | None = None


class EhLoginRequest(BaseModel):
    username: str
    password: str


class PixivTokenRequest(BaseModel):
    refresh_token: str


class PixivCookieRequest(BaseModel):
    phpsessid: str


class PixivOAuthCallbackRequest(BaseModel):
    code: str
    code_verifier: str


class FeatureTogglePatch(BaseModel):
    enabled: bool | None = None
    value: int | float | None = None


class EhSitePreference(BaseModel):
    use_ex: bool


class GenericCookieRequest(BaseModel):
    source: str
    cookies: dict[str, str]


# ── Credentials ──────────────────────────────────────────────────────


@router.get("/credentials")
async def list_credentials_endpoint(_: dict = Depends(_admin)):
    """Which credential sources are configured (values never exposed)."""
    all_creds = await list_credentials()
    result = {}
    for c in all_creds:
        result[c["source"]] = {"configured": True}
    return result


@router.post("/credentials/ehentai/login")
async def eh_login_with_password(
    req: EhLoginRequest,
    _: dict = Depends(_admin),
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
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                "Referer": "https://forums.e-hentai.org/index.php?act=Login&CODE=00",
                "Origin": "https://forums.e-hentai.org",
            },
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
        resp2 = await client.get(
            "https://e-hentai.org/",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"},
        )
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
            ex_resp = await ex_client.get(
                "https://exhentai.org/",
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"},
            )
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
    _: dict = Depends(_admin),
):
    """Save E-Hentai cookies (no server-side validation — same as EhViewer)."""
    cookies = {
        "ipb_member_id": req.ipb_member_id,
        "ipb_pass_hash": req.ipb_pass_hash,
    }
    if req.sk:
        cookies["sk"] = req.sk
    if req.igneous:
        cookies["igneous"] = req.igneous

    await set_credential("ehentai", json.dumps(cookies), "cookie")

    # Try to fetch account info but don't fail if it doesn't work
    account: dict = {}
    try:
        use_ex = bool(req.igneous)
        async with EhClient(cookies=cookies, use_ex=use_ex) as client:
            account = await client.get_account_info()
    except Exception as exc:
        logger.warning("EH account info fetch failed (cookies saved anyway): %s", exc)

    return {"status": "ok", "account": account}


@router.post("/credentials/pixiv")
async def set_pixiv_credentials(
    req: PixivTokenRequest,
    _: dict = Depends(_admin),
):
    """Save Pixiv refresh_token after verifying it via pixivpy3."""
    try:
        import asyncio as _asyncio

        import pixivpy3

        api = pixivpy3.AppPixivAPI()
        await _asyncio.to_thread(api.auth, refresh_token=req.refresh_token)
        detail = await _asyncio.to_thread(api.user_detail, api.user_id)
        username = detail.user.name
    except (ImportError, AttributeError, ValueError, OSError) as exc:
        logger.error("Pixiv auth failed: %s", exc)
        raise HTTPException(status_code=400, detail=f"Pixiv auth failed: {exc}")

    await set_credential("pixiv", req.refresh_token, "oauth_token")
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
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        
        async with httpx.AsyncClient(follow_redirects=False) as client:
            resp = await client.get(auth_url, cookies=cookies, headers=headers)
            
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
        headers_exchange = {
            "User-Agent": "PixivAndroidApp/5.0.234 (Android 11; Pixel 5)",
            "App-OS-Version": "11",
            "App-OS": "android",
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://oauth.secure.pixiv.net/auth/token", 
                data=data, 
                headers=headers_exchange
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
    await set_credential("pixiv", refresh_token, "oauth_token")
    return {"status": "ok", "username": username}



@router.post("/credentials/generic")
async def set_generic_cookie(
    req: GenericCookieRequest,
    _: dict = Depends(_admin),
):
    """Save cookies for any site (twitter, instagram, danbooru, etc.)."""
    if not req.source.strip():
        raise HTTPException(status_code=400, detail="Source name is required")
    if not req.cookies:
        raise HTTPException(status_code=400, detail="At least one cookie is required")
    await set_credential(req.source.strip().lower(), json.dumps(req.cookies), "cookie")
    return {"status": "ok", "source": req.source.strip().lower()}


@router.delete("/credentials/{source}")
async def delete_credential_endpoint(
    source: str,
    _: dict = Depends(_admin),
):
    """Delete stored credential for a source."""
    async with async_session() as session:
        result = await session.execute(
            select(Credential).where(Credential.source == source)
        )
        cred = result.scalar_one_or_none()
        if not cred:
            raise HTTPException(status_code=404, detail="No credential found")
        await session.delete(cred)
        await session.commit()
    return {"status": "ok"}


# ── ExHentai cookie check ─────────────────────────────────────────────


@router.post("/credentials/ehentai/cookies-check")
async def eh_cookies_check(_: dict = Depends(_admin)):
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
async def eh_account_info(_: dict = Depends(_admin)):
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


# ── Feature Toggle Helpers ───────────────────────────────────────────


async def _get_toggle(redis_key: str, default: bool) -> bool:
    """Read a boolean toggle from Redis, falling back to config default."""
    val = await get_redis().get(redis_key)
    if val is not None:
        return val == b"1"
    return default


async def _set_toggle(redis_key: str, enabled: bool) -> bool:
    """Set a boolean toggle in Redis."""
    await get_redis().set(redis_key, "1" if enabled else "0")
    return enabled


async def _get_int_setting(redis_key: str, default: int) -> int:
    """Read an integer setting from Redis, falling back to default."""
    val = await get_redis().get(redis_key)
    if val is not None:
        try:
            return int(val)
        except (ValueError, TypeError):
            pass
    return default


async def _get_float_setting(redis_key: str, default: float) -> float:
    """Read a float setting from Redis, falling back to default."""
    val = await get_redis().get(redis_key)
    if val is not None:
        try:
            return float(val)
        except (ValueError, TypeError):
            pass
    return default


# ── Feature Toggles ──────────────────────────────────────────────────


@router.get("/features")
async def get_feature_toggles(_: dict = Depends(require_auth)):
    """Get all feature toggle states."""
    return {
        "csrf_enabled": await _get_toggle("setting:csrf_enabled", app_settings.csrf_enabled),
        "rate_limit_enabled": await _get_toggle("setting:rate_limit_enabled", app_settings.rate_limit_enabled),
        "opds_enabled": await _get_toggle("setting:opds_enabled", app_settings.opds_enabled),
        "external_api_enabled": await _get_toggle("setting:external_api_enabled", app_settings.external_api_enabled),
        "ai_tagging_enabled": await _get_toggle("setting:ai_tagging_enabled", app_settings.tag_model_enabled),
        "download_eh_enabled": await _get_toggle("setting:download_eh_enabled", app_settings.download_eh_enabled),
        "download_pixiv_enabled": await _get_toggle("setting:download_pixiv_enabled", app_settings.download_pixiv_enabled),
        "download_gallery_dl_enabled": await _get_toggle("setting:download_gallery_dl_enabled", app_settings.download_gallery_dl_enabled),
        "dedup_phash_enabled": await _get_toggle("setting:dedup_phash_enabled", False),
        "dedup_heuristic_enabled": await _get_toggle("setting:dedup_heuristic_enabled", False),
        "dedup_phash_threshold": await _get_int_setting("setting:dedup_phash_threshold", 10),
        "dedup_opencv_enabled": await _get_toggle("setting:dedup_opencv_enabled", False),
        "dedup_opencv_threshold": await _get_float_setting("setting:dedup_opencv_threshold", 0.85),
        "retry_enabled": await _get_toggle("setting:retry_enabled", True),
        "retry_max_retries": await _get_int_setting("setting:retry_max_retries", 3),
        "retry_base_delay_minutes": await _get_int_setting("setting:retry_base_delay_minutes", 5),
    }


@router.patch("/features/{feature}")
async def patch_feature_toggle(
    feature: str,
    req: FeatureTogglePatch,
    _: dict = Depends(_admin),
):
    """Toggle a feature on/off."""
    ALLOWED = {
        "csrf_enabled": "setting:csrf_enabled",
        "rate_limit_enabled": None,  # special case: modifies app_settings directly
        "opds_enabled": "setting:opds_enabled",
        "external_api_enabled": "setting:external_api_enabled",
        "ai_tagging_enabled": "setting:ai_tagging_enabled",
        "download_eh_enabled": "setting:download_eh_enabled",
        "download_pixiv_enabled": "setting:download_pixiv_enabled",
        "download_gallery_dl_enabled": "setting:download_gallery_dl_enabled",
        "dedup_phash_enabled": "setting:dedup_phash_enabled",
        "dedup_heuristic_enabled": "setting:dedup_heuristic_enabled",
        "dedup_phash_threshold": "setting:dedup_phash_threshold",
        "dedup_opencv_enabled": "setting:dedup_opencv_enabled",
        "dedup_opencv_threshold": "setting:dedup_opencv_threshold",
        "retry_enabled": "setting:retry_enabled",
        "retry_max_retries": "setting:retry_max_retries",
        "retry_base_delay_minutes": "setting:retry_base_delay_minutes",
    }
    if feature not in ALLOWED:
        raise HTTPException(status_code=400, detail=f"Unknown feature: {feature}")

    redis_key = ALLOWED.get(feature)

    if feature == "dedup_phash_threshold":
        if req.value is None:
            raise HTTPException(status_code=400, detail="value required for dedup_phash_threshold")
        await get_redis().set("setting:dedup_phash_threshold", str(req.value))
        return {"feature": feature, "value": req.value}

    if feature == "dedup_opencv_threshold":
        if req.value is None:
            raise HTTPException(status_code=400, detail="value required for dedup_opencv_threshold")
        await get_redis().set("setting:dedup_opencv_threshold", str(req.value))
        return {"feature": feature, "value": req.value}

    if feature == "retry_max_retries":
        if req.value is None:
            raise HTTPException(status_code=400, detail="value required for retry_max_retries")
        val = int(req.value)
        if not (1 <= val <= 10):
            raise HTTPException(status_code=400, detail="retry_max_retries must be between 1 and 10")
        await get_redis().set("setting:retry_max_retries", str(val))
        return {"feature": feature, "value": val}

    if feature == "retry_base_delay_minutes":
        if req.value is None:
            raise HTTPException(status_code=400, detail="value required for retry_base_delay_minutes")
        val = int(req.value)
        if not (1 <= val <= 60):
            raise HTTPException(status_code=400, detail="retry_base_delay_minutes must be between 1 and 60")
        await get_redis().set("setting:retry_base_delay_minutes", str(val))
        return {"feature": feature, "value": val}

    if req.enabled is None:
        raise HTTPException(status_code=400, detail="enabled required for boolean features")

    if feature == "rate_limit_enabled":
        app_settings.rate_limit_enabled = req.enabled
        await get_redis().set("setting:rate_limit_enabled", "1" if req.enabled else "0")
        return {"feature": feature, "enabled": req.enabled}

    await _set_toggle(redis_key, req.enabled)
    return {"feature": feature, "enabled": req.enabled}


# ── EH Site Preference ───────────────────────────────────────────────


@router.get("/eh-site")
async def get_eh_site_preference(_: dict = Depends(require_auth)):
    """Get current E-Hentai / ExHentai preference."""
    redis = get_redis()
    pref = await redis.get("setting:eh_use_ex")
    if pref is not None:
        use_ex = pref == b"1"
    else:
        use_ex = app_settings.eh_use_ex
    return {"use_ex": use_ex}


@router.patch("/eh-site")
async def set_eh_site_preference(
    req: EhSitePreference,
    _: dict = Depends(_admin),
):
    """Toggle between E-Hentai and ExHentai."""
    redis = get_redis()
    await redis.set("setting:eh_use_ex", "1" if req.use_ex else "0")
    return {"use_ex": req.use_ex}


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
async def list_tokens(auth: dict = Depends(_member)):
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


_MAX_TOKEN_EXPIRY_DAYS = 365


@router.post("/tokens")
async def create_token(
    req: CreateTokenRequest,
    auth: dict = Depends(_member),
):
    """Create a new API token."""
    if req.expires_days is not None and req.expires_days > _MAX_TOKEN_EXPIRY_DAYS:
        raise HTTPException(
            status_code=400,
            detail=f"expires_days must be <= {_MAX_TOKEN_EXPIRY_DAYS}",
        )

    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

    expires_at = None
    if req.expires_days and req.expires_days > 0:
        from datetime import timedelta

        expires_at = datetime.now(UTC) + timedelta(days=req.expires_days)

    async with async_session() as session:
        result = await session.execute(
            text("""
                INSERT INTO api_tokens (user_id, name, token_hash, expires_at)
                VALUES (:uid, :name, :hash, :exp)
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
    auth: dict = Depends(_member),
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
    auth: dict = Depends(_member),
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


# ── Rate Limit Models ─────────────────────────────────────────────────


class SiteRateConfig(BaseModel):
    concurrency: int | None = None
    delay_ms: int | None = None
    image_concurrency: int | None = None
    page_delay_ms: int | None = None
    pagination_delay_ms: int | None = None
    illust_delay_ms: int | None = None


class RateLimitSchedule(BaseModel):
    enabled: bool | None = None
    start_hour: int | None = None
    end_hour: int | None = None
    mode: str | None = None


class RateLimitSettings(BaseModel):
    sites: dict[str, SiteRateConfig] | None = None
    schedule: RateLimitSchedule | None = None


class RateLimitOverride(BaseModel):
    unlocked: bool


# ── Rate Limit Endpoints ──────────────────────────────────────────────


async def _build_rate_limit_response(redis) -> dict:
    """Read current rate limit config from Redis and return the full response dict."""

    async def _read_int(key: str, default: int) -> int:
        val = await redis.get(key)
        if val is not None:
            try:
                return int(val)
            except (ValueError, TypeError):
                pass
        return default

    async def _read_str(key: str, default: str) -> str:
        val = await redis.get(key)
        if val is not None:
            if isinstance(val, bytes):
                return val.decode()
            return str(val)
        return default

    async def _read_bool(key: str, default: bool) -> bool:
        val = await redis.get(key)
        if val is not None:
            return val in (b"1", "1")
        return default

    eh_concurrency = await _read_int("rate_limit:config:ehentai:concurrency", app_settings.eh_max_concurrency)
    eh_delay_ms = await _read_int("rate_limit:config:ehentai:delay_ms", 0)
    eh_image_concurrency = await _read_int("rate_limit:config:ehentai:image_concurrency", app_settings.eh_download_concurrency)

    pixiv_concurrency = await _read_int("rate_limit:config:pixiv:concurrency", 2)
    pixiv_page_delay = await _read_int("rate_limit:config:pixiv:page_delay_ms", 500)
    pixiv_pagination_delay = await _read_int("rate_limit:config:pixiv:pagination_delay_ms", 1000)
    pixiv_illust_delay = await _read_int("rate_limit:config:pixiv:illust_delay_ms", 2000)

    gdl_concurrency = await _read_int("rate_limit:config:gallery_dl:concurrency", 1)
    gdl_delay_ms = await _read_int("rate_limit:config:gallery_dl:delay_ms", 0)

    schedule_enabled = await _read_bool("rate_limit:schedule:enabled", False)
    schedule_start_hour = await _read_int("rate_limit:schedule:start_hour", 0)
    schedule_end_hour = await _read_int("rate_limit:schedule:end_hour", 6)
    schedule_mode = await _read_str("rate_limit:schedule:mode", "full_speed")

    override_val = await redis.get("rate_limit:override:unlocked")
    override_active = override_val is not None

    schedule_active_val = await redis.get("rate_limit:schedule:active")
    schedule_active = schedule_active_val in (b"1", "1")

    return {
        "sites": {
            "ehentai": {
                "concurrency": eh_concurrency,
                "delay_ms": eh_delay_ms,
                "image_concurrency": eh_image_concurrency,
            },
            "pixiv": {
                "concurrency": pixiv_concurrency,
                "delay_ms": None,
                "image_concurrency": None,
                "page_delay_ms": pixiv_page_delay,
                "pagination_delay_ms": pixiv_pagination_delay,
                "illust_delay_ms": pixiv_illust_delay,
            },
            "gallery_dl": {
                "concurrency": gdl_concurrency,
                "delay_ms": gdl_delay_ms,
                "image_concurrency": None,
            },
        },
        "schedule": {
            "enabled": schedule_enabled,
            "start_hour": schedule_start_hour,
            "end_hour": schedule_end_hour,
            "mode": schedule_mode,
        },
        "override_active": override_active,
        "schedule_active": schedule_active,
    }


@router.get("/rate-limits")
async def get_rate_limits(_: dict = Depends(_admin)):
    """Get current download rate limit configuration."""
    redis = get_redis()
    return await _build_rate_limit_response(redis)


@router.patch("/rate-limits")
async def patch_rate_limits(
    req: RateLimitSettings,
    _: dict = Depends(_admin),
):
    """Partially update download rate limit configuration."""
    redis = get_redis()

    def _validate_concurrency(v: int | None, field: str) -> None:
        if v is not None and not (1 <= v <= 10):
            raise HTTPException(status_code=400, detail=f"{field} must be between 1 and 10")

    def _validate_delay_ms(v: int | None, field: str) -> None:
        if v is not None and not (0 <= v <= 10000):
            raise HTTPException(status_code=400, detail=f"{field} must be between 0 and 10000")

    def _validate_hour(v: int | None, field: str) -> None:
        if v is not None and not (0 <= v <= 23):
            raise HTTPException(status_code=400, detail=f"{field} must be between 0 and 23")

    _VALID_SOURCES = {"ehentai", "pixiv", "gallery_dl"}

    if req.sites:
        for source, cfg in req.sites.items():
            if source not in _VALID_SOURCES:
                raise HTTPException(status_code=400, detail=f"Unknown source: {source}")
            _validate_concurrency(cfg.concurrency, f"{source}.concurrency")
            _validate_delay_ms(cfg.delay_ms, f"{source}.delay_ms")
            _validate_concurrency(cfg.image_concurrency, f"{source}.image_concurrency")
            _validate_delay_ms(cfg.page_delay_ms, f"{source}.page_delay_ms")
            _validate_delay_ms(cfg.pagination_delay_ms, f"{source}.pagination_delay_ms")
            _validate_delay_ms(cfg.illust_delay_ms, f"{source}.illust_delay_ms")

            if cfg.concurrency is not None:
                await redis.set(f"rate_limit:config:{source}:concurrency", str(cfg.concurrency))
            if cfg.delay_ms is not None:
                await redis.set(f"rate_limit:config:{source}:delay_ms", str(cfg.delay_ms))
            if cfg.image_concurrency is not None:
                await redis.set(f"rate_limit:config:{source}:image_concurrency", str(cfg.image_concurrency))
            if cfg.page_delay_ms is not None:
                await redis.set(f"rate_limit:config:{source}:page_delay_ms", str(cfg.page_delay_ms))
            if cfg.pagination_delay_ms is not None:
                await redis.set(f"rate_limit:config:{source}:pagination_delay_ms", str(cfg.pagination_delay_ms))
            if cfg.illust_delay_ms is not None:
                await redis.set(f"rate_limit:config:{source}:illust_delay_ms", str(cfg.illust_delay_ms))

    if req.schedule:
        sched = req.schedule
        _validate_hour(sched.start_hour, "schedule.start_hour")
        _validate_hour(sched.end_hour, "schedule.end_hour")

        if sched.enabled is not None:
            await redis.set("rate_limit:schedule:enabled", "1" if sched.enabled else "0")
        if sched.start_hour is not None:
            await redis.set("rate_limit:schedule:start_hour", str(sched.start_hour))
        if sched.end_hour is not None:
            await redis.set("rate_limit:schedule:end_hour", str(sched.end_hour))
        if sched.mode is not None:
            if sched.mode not in ("full_speed", "standard"):
                raise HTTPException(status_code=400, detail="schedule.mode must be 'full_speed' or 'standard'")
            await redis.set("rate_limit:schedule:mode", sched.mode)

        # Immediately evaluate schedule_active so the response reflects the current state
        enabled_val = await redis.get("rate_limit:schedule:enabled")
        enabled = enabled_val in (b"1", "1")

        if not enabled:
            await redis.delete("rate_limit:schedule:active")
        else:
            start_val = await redis.get("rate_limit:schedule:start_hour")
            end_val = await redis.get("rate_limit:schedule:end_hour")
            try:
                start_hour = int(start_val) if start_val is not None else 0
            except (ValueError, TypeError):
                start_hour = 0
            try:
                end_hour = int(end_val) if end_val is not None else 6
            except (ValueError, TypeError):
                end_hour = 6

            current_hour = datetime.now(timezone.utc).hour
            if start_hour <= end_hour:
                in_window = start_hour <= current_hour < end_hour
            else:
                in_window = current_hour >= start_hour or current_hour < end_hour

            if in_window:
                await redis.set("rate_limit:schedule:active", "1")
            else:
                await redis.delete("rate_limit:schedule:active")

    return await _build_rate_limit_response(redis)


@router.post("/rate-limits/override")
async def set_rate_limit_override(
    req: RateLimitOverride,
    _: dict = Depends(_admin),
):
    """Set or clear the rate limit boost override."""
    redis = get_redis()
    if req.unlocked:
        await redis.set("rate_limit:override:unlocked", "1")
    else:
        await redis.delete("rate_limit:override:unlocked")
    return {"override_active": req.unlocked}
