"""Per-source credential accounts: list, switch the active one, delete (ADR 0019)."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.auth import require_role
from services.cache import purge_account_scoped_cache
from services.credential import ACCOUNT_PATTERN, activate_account, delete_account, list_accounts

router = APIRouter(tags=["credentials"])

_admin = require_role("admin")


class ActivateAccountRequest(BaseModel):
    account: str = Field(pattern=ACCOUNT_PATTERN)


@router.get("/{source}/accounts")
async def list_accounts_endpoint(source: str, _: dict = Depends(_admin)):
    """Accounts stored for a source (values never exposed)."""
    return {"source": source, "accounts": await list_accounts(source)}


@router.post("/{source}/active")
async def activate_account_endpoint(source: str, req: ActivateAccountRequest, _: dict = Depends(_admin)):
    """Switch which account new downloads, subscription checks and browsing use."""
    if not await activate_account(source, req.account):
        raise HTTPException(status_code=404, detail="Account not found")
    await purge_account_scoped_cache(source)
    return {"status": "ok", "source": source, "account": req.account}


@router.delete("/{source}/accounts/{account}")
async def delete_account_endpoint(source: str, account: str, _: dict = Depends(_admin)):
    """Delete one account. The active account can only go when it is the last one."""
    outcome = await delete_account(source, account)
    if outcome == "not_found":
        raise HTTPException(status_code=404, detail="Account not found")
    if outcome == "active_in_use":
        raise HTTPException(status_code=409, detail="Switch to another account before deleting the active one")
    return {"status": "ok"}
