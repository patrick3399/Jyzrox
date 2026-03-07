"""Credential management and system settings."""

import json
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.auth import require_auth
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


class EhLoginRequest(BaseModel):
    username: str
    password: str


class PixivTokenRequest(BaseModel):
    refresh_token: str


# ── Credentials ──────────────────────────────────────────────────────

@router.get("/credentials")
async def list_credentials(_: dict = Depends(require_auth)):
    """Which credential sources are configured (values never exposed)."""
    sources = ["ehentai", "pixiv"]
    return {
        src: {"configured": (await get_credential(src)) is not None}
        for src in sources
    }


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
    async with EhClient(cookies=cookies) as client:
        if not await client.check_cookies():
            raise HTTPException(status_code=400, detail="Login succeeded but cookies are invalid")
        account = await client.get_account_info()

    await set_credential("ehentai", json.dumps(cookies), "cookie")
    return {"status": "ok", "account": account}


@router.post("/credentials/ehentai")
async def set_eh_credentials(
    req: EhCookieRequest,
    _: dict = Depends(require_auth),
):
    """Save E-Hentai cookies after verifying them."""
    cookies = {
        "ipb_member_id": req.ipb_member_id,
        "ipb_pass_hash": req.ipb_pass_hash,
        "sk":            req.sk,
    }
    async with EhClient(cookies=cookies) as client:
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
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Pixiv auth failed: {exc}")

    await set_credential("pixiv", req.refresh_token, "oauth_token")
    return {"status": "ok", "username": username}


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


# ── Alerts ───────────────────────────────────────────────────────────

@router.get("/alerts")
async def get_alerts(_: dict = Depends(require_auth)):
    """Return queued system alerts (cookie expiry, etc.)."""
    return {"alerts": await get_system_alerts()}
