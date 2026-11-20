"""Settings: credential listing and E-Hentai credentials."""

import json
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException

from core.auth import require_role
from core.client_identity import browser_headers
from services.browser_http import browser_client
from services.credential import list_credentials, set_credential
from services.eh_client import EhClient
from services.settings_schemas import (
    EhCookieRequest,
    EhLoginRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter()

_admin = require_role("admin")
_member = require_role("member")


@router.get("/credentials")
async def list_credentials_endpoint(_: dict = Depends(_admin)):
    """Which credential sources are configured (values never exposed)."""
    all_creds = await list_credentials()
    result = {}
    for c in all_creds:
        result[c["source"]] = {"configured": True, "account": c.get("account"), "accounts": c.get("accounts", 1)}
    return result


@router.post("/credentials/ehentai/login")
async def eh_login_with_password(
    req: EhLoginRequest,
    _: dict = Depends(_admin),
):
    """Login to E-Hentai with username/password to auto-obtain cookies (EhViewer-style)."""
    async with browser_client(follow_redirects=True, timeout=30) as client:
        resp = await client.post(
            "https://forums.e-hentai.org/index.php?act=Login&CODE=01",
            data={
                "UserName": req.username,
                "PassWord": req.password,
                "submit": "Log me in",
                "CookieDate": "1",
                "temporary_https": "off",
            },
            headers=browser_headers(
                "document",
                site="same-origin",
                referer="https://forums.e-hentai.org/index.php?act=Login&CODE=00",
                origin="https://forums.e-hentai.org",
            ),
        )

    ipb_member_id = resp.cookies.get("ipb_member_id")
    ipb_pass_hash = resp.cookies.get("ipb_pass_hash")
    if not ipb_member_id or not ipb_pass_hash:
        raise HTTPException(status_code=400, detail="Login failed: incorrect username or password")

    # Fetch sk cookie from main EH page
    async with browser_client(
        cookies={"ipb_member_id": ipb_member_id, "ipb_pass_hash": ipb_pass_hash},
        follow_redirects=True,
        timeout=15,
    ) as client:
        resp2 = await client.get(
            "https://e-hentai.org/",
            headers=browser_headers("document", site="none"),
        )
    sk = resp2.cookies.get("sk", "")

    cookies = {"ipb_member_id": ipb_member_id, "ipb_pass_hash": ipb_pass_hash, "sk": sk}

    # Try to obtain igneous cookie for ExHentai access
    igneous = None
    try:
        async with browser_client(
            cookies=cookies,
            follow_redirects=True,
            timeout=15,
        ) as ex_client:
            ex_resp = await ex_client.get(
                "https://exhentai.org/",
                headers=browser_headers("document", site="none"),
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
    try:
        async with EhClient(cookies=cookies, use_ex=use_ex) as client:
            if not await client.check_cookies():
                raise HTTPException(status_code=400, detail="Login succeeded but cookies are invalid")
            account = await client.get_account_info()
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("EH cookie validation failed: %s", exc)
        raise HTTPException(status_code=502, detail="Failed to validate cookies with E-Hentai") from None

    await set_credential("ehentai", json.dumps(cookies), "cookie", account=req.account)
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

    await set_credential("ehentai", json.dumps(cookies), "cookie", account=req.account)

    # Try to fetch account info but don't fail if it doesn't work
    account: dict = {}
    try:
        use_ex = bool(req.igneous)
        async with EhClient(cookies=cookies, use_ex=use_ex) as client:
            account = await client.get_account_info()
    except Exception as exc:
        logger.warning("EH account info fetch failed (cookies saved anyway): %s", exc)

    return {"status": "ok", "account": account}
