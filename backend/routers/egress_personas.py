"""Egress personas: admin CRUD, account binding and exit-IP test (ADR 0022)."""

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from core.auth import require_role
from services.credential import ACCOUNT_PATTERN
from services.egress_persona import (
    CredentialAccountNotFound,
    PersonaConflict,
    PersonaNotFound,
    bind_account,
    create_persona,
    delete_persona,
    list_personas,
    test_persona_egress,
    unbind_account,
    update_persona,
)

router = APIRouter(tags=["personas"])

_admin = require_role("admin")
_NAME = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$"


class PersonaCreate(BaseModel):
    name: str = Field(pattern=_NAME)
    proxy_url: str | None = None
    user_agent: str | None = None
    browser_profile: str | None = None
    enabled: bool = True


class PersonaUpdate(BaseModel):
    name: str | None = Field(default=None, pattern=_NAME)
    proxy_url: str | None = None
    user_agent: str | None = None
    browser_profile: str | None = None
    enabled: bool | None = None


class BindRequest(BaseModel):
    account: str = Field(pattern=ACCOUNT_PATTERN)


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, PersonaNotFound):
        return HTTPException(status_code=404, detail="Persona not found")
    if isinstance(exc, CredentialAccountNotFound):
        return HTTPException(status_code=404, detail=f"Credential account not found: {exc}")
    if isinstance(exc, PersonaConflict):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


@router.get("")
async def list_endpoint(_: dict = Depends(_admin)):
    return await list_personas()


@router.post("", status_code=201)
async def create_endpoint(req: PersonaCreate, _: dict = Depends(_admin)):
    try:
        return await create_persona(req.model_dump())
    except (PersonaConflict, ValueError) as exc:
        raise _http(exc) from exc


@router.patch("/{persona_id}")
async def update_endpoint(persona_id: int, req: PersonaUpdate, _: dict = Depends(_admin)):
    try:
        return await update_persona(persona_id, req.model_dump(exclude_unset=True))
    except (PersonaNotFound, PersonaConflict, ValueError) as exc:
        raise _http(exc) from exc


@router.delete("/{persona_id}", status_code=204)
async def delete_endpoint(persona_id: int, _: dict = Depends(_admin)):
    try:
        await delete_persona(persona_id)
    except PersonaNotFound as exc:
        raise _http(exc) from exc
    return Response(status_code=204)


@router.put("/{persona_id}/accounts/{source}")
async def bind_endpoint(persona_id: int, source: str, req: BindRequest, _: dict = Depends(_admin)):
    try:
        return await bind_account(persona_id, source, req.account)
    except (PersonaNotFound, CredentialAccountNotFound, PersonaConflict) as exc:
        raise _http(exc) from exc


@router.delete("/{persona_id}/accounts/{source}", status_code=204)
async def unbind_endpoint(persona_id: int, source: str, _: dict = Depends(_admin)):
    try:
        await unbind_account(persona_id, source)
    except PersonaNotFound as exc:
        raise _http(exc) from exc
    return Response(status_code=204)


@router.post("/{persona_id}/test")
async def test_endpoint(persona_id: int, _: dict = Depends(_admin)):
    try:
        return await test_persona_egress(persona_id)
    except PersonaNotFound as exc:
        raise _http(exc) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Egress test failed: {exc}") from exc
