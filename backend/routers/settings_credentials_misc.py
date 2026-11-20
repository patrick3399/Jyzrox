"""Settings: SauceNAO, generic and site credentials, E-Hentai cookie checks."""

import json
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from core.auth import require_role
from services.cache import push_system_alert
from services.credential import delete_account, get_credential, set_credential
from services.eh_client import EhClient
from services.settings_schemas import (
    GenericCookieRequest,
    SaucenaoApiKeyRequest,
    SiteCredentialRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter()

_admin = require_role("admin")
_member = require_role("member")


@router.post("/credentials/saucenao")
async def set_saucenao_credential(
    req: SaucenaoApiKeyRequest,
    _: dict = Depends(_admin),
):
    """Save SauceNAO API key."""
    api_key = req.api_key.strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="API key is required")
    await set_credential("saucenao", api_key, "api_key", account=req.account)
    return {"status": "ok"}


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
    await set_credential(req.source.strip().lower(), json.dumps(req.cookies), "cookie", account=req.account)
    return {"status": "ok", "source": req.source.strip().lower()}


@router.post("/credentials/site")
async def set_site_credential(req: SiteCredentialRequest, _: dict = Depends(_admin)):
    """Save credentials for any gallery-dl site as a config fragment."""
    source = req.source.strip().lower()
    if not source:
        raise HTTPException(status_code=400, detail="Source name is required")

    fragment: dict = {}
    if req.cookies:
        from services.credential import parse_cookie_input

        parsed = parse_cookie_input(req.cookies)
        if not parsed:
            raise HTTPException(status_code=400, detail="Could not parse cookies")
        fragment["cookies"] = parsed
    if req.username:
        fragment["username"] = req.username
        if req.password:
            fragment["password"] = req.password
    if not fragment:
        raise HTTPException(status_code=400, detail="Cookies or username is required")

    await set_credential(source, json.dumps(fragment), "gdl_fragment", account=req.account)
    return {"status": "ok", "source": source}


@router.get("/credentials/detect")
async def detect_site_from_url(url: str = Query(...), _: dict = Depends(_admin)):
    """Detect gallery-dl site from a URL."""
    try:
        from gallery_dl import extractor as gdl_extractor

        ex = gdl_extractor.find(url)
        if not ex or not getattr(ex, "category", None):
            return {"detected": False}
        category = ex.category
        from services.site_catalog import get_site_config

        cfg = get_site_config(category)
        display_name = cfg.name if cfg.source_id != "gallery_dl" else category.capitalize()
        return {"detected": True, "source": category, "site_name": display_name}
    except Exception:
        return {"detected": False}


@router.delete("/credentials/{source}")
async def delete_credential_endpoint(
    source: str,
    _: dict = Depends(_admin),
):
    """Delete the stored credential of a source that has a single account."""
    outcome = await delete_account(source)
    if outcome == "not_found":
        raise HTTPException(status_code=404, detail="No credential found")
    if outcome == "active_in_use":
        raise HTTPException(status_code=409, detail="This source has several accounts; delete them one by one")
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


# ── Feature Toggles ──────────────────────────────────────────────────
