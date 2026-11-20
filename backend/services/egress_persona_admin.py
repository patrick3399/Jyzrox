"""Egress persona admin: CRUD, account binding and exit-IP test (ADR 0022)."""

from __future__ import annotations

import ipaddress
from datetime import UTC, datetime

import httpx
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import AsyncSessionLocal
from db.models import Credential, EgressPersona, PersonaAccount

TRACE_URL = "https://www.cloudflare.com/cdn-cgi/trace"

# ── Admin CRUD ────────────────────────────────────────────────────────


class PersonaNotFound(Exception):
    pass


class PersonaConflict(Exception):
    pass


class CredentialAccountNotFound(Exception):
    pass


def validate_persona_fields(*, proxy_url: str | None, user_agent: str | None, browser_profile: str | None) -> None:
    # No SOCKS, same reason as site_config.proxy_url: the gallery-dl venv has no PySocks.
    if proxy_url is not None and not proxy_url.startswith(("http://", "https://")):
        raise ValueError("proxy_url must start with http:// or https:// (SOCKS proxies are not supported)")
    if browser_profile not in (None, "chrome", "firefox"):
        raise ValueError("browser_profile must be 'chrome', 'firefox', or null")
    if browser_profile is not None and user_agent is not None:
        raise ValueError("set either browser_profile or user_agent, not both")
    if user_agent is not None and (len(user_agent) > 512 or "\n" in user_agent or "\r" in user_agent):
        raise ValueError("user_agent must be a single line of at most 512 characters")


def _serialize(persona: EgressPersona, accounts: list[PersonaAccount]) -> dict:
    return {
        "id": persona.id,
        "name": persona.name,
        "proxy_url": persona.proxy_url,
        "user_agent": persona.user_agent,
        "browser_profile": persona.browser_profile,
        "enabled": persona.enabled,
        "last_exit_ip": persona.last_exit_ip,
        "last_tested_at": persona.last_tested_at.isoformat() if persona.last_tested_at else None,
        "accounts": [{"source": a.source, "account": a.account} for a in accounts],
    }


async def _accounts_of(session: AsyncSession, persona_id: int) -> list[PersonaAccount]:
    return list(
        (
            await session.execute(
                select(PersonaAccount).where(PersonaAccount.persona_id == persona_id).order_by(PersonaAccount.source)
            )
        ).scalars()
    )


async def list_personas() -> list[dict]:
    async with AsyncSessionLocal() as session:
        personas = list((await session.execute(select(EgressPersona).order_by(EgressPersona.id))).scalars())
        return [_serialize(p, await _accounts_of(session, p.id)) for p in personas]


async def create_persona(data: dict) -> dict:
    validate_persona_fields(
        proxy_url=data.get("proxy_url"), user_agent=data.get("user_agent"), browser_profile=data.get("browser_profile")
    )
    async with AsyncSessionLocal() as session:
        persona = EgressPersona(
            name=data["name"],
            proxy_url=data.get("proxy_url"),
            user_agent=data.get("user_agent"),
            browser_profile=data.get("browser_profile"),
            enabled=data.get("enabled", True),
        )
        session.add(persona)
        try:
            await session.commit()
        except IntegrityError as exc:
            raise PersonaConflict(f"A persona named {data['name']!r} already exists") from exc
        return _serialize(persona, [])


async def update_persona(persona_id: int, data: dict) -> dict:
    async with AsyncSessionLocal() as session:
        persona = await session.get(EgressPersona, persona_id)
        if persona is None:
            raise PersonaNotFound(persona_id)
        for field in ("name", "enabled"):
            # NOT NULL columns: an explicit null would surface as a misleading 409.
            if field in data and data[field] is None:
                raise ValueError(f"{field} cannot be null")
        merged = {
            "proxy_url": data.get("proxy_url", persona.proxy_url),
            "user_agent": data.get("user_agent", persona.user_agent),
            "browser_profile": data.get("browser_profile", persona.browser_profile),
        }
        validate_persona_fields(**merged)
        for field in ("name", "proxy_url", "user_agent", "browser_profile", "enabled"):
            if field in data:
                setattr(persona, field, data[field])
        try:
            await session.commit()
        except IntegrityError as exc:
            raise PersonaConflict(f"A persona named {data.get('name')!r} already exists") from exc
        return _serialize(persona, await _accounts_of(session, persona_id))


async def delete_persona(persona_id: int) -> None:
    """Running jobs keep the identity they loaded; their persona_id becomes NULL."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(delete(EgressPersona).where(EgressPersona.id == persona_id))
        await session.commit()
        if not result.rowcount:
            raise PersonaNotFound(persona_id)


async def bind_account(persona_id: int, source: str, account: str) -> dict:
    async with AsyncSessionLocal() as session:
        if await session.get(EgressPersona, persona_id) is None:
            raise PersonaNotFound(persona_id)
        if await session.get(Credential, (source, account)) is None:
            raise CredentialAccountNotFound(f"{source}/{account}")
        await session.execute(
            delete(PersonaAccount).where(PersonaAccount.persona_id == persona_id, PersonaAccount.source == source)
        )
        session.add(PersonaAccount(persona_id=persona_id, source=source, account=account))
        try:
            await session.commit()
        except IntegrityError as exc:
            raise PersonaConflict(f"{source}/{account} is already bound to another persona") from exc
        persona = await session.get(EgressPersona, persona_id)
        return _serialize(persona, await _accounts_of(session, persona_id))


async def unbind_account(persona_id: int, source: str) -> None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            delete(PersonaAccount).where(PersonaAccount.persona_id == persona_id, PersonaAccount.source == source)
        )
        await session.commit()
        if not result.rowcount:
            raise PersonaNotFound(persona_id)


def _same_subnet(a: str, b: str) -> bool:
    try:
        ia, ib = ipaddress.ip_address(a), ipaddress.ip_address(b)
    except ValueError:
        return False
    if ia.version != 4 or ib.version != 4:
        return False
    return ipaddress.ip_network(f"{a}/24", strict=False) == ipaddress.ip_network(f"{b}/24", strict=False)


async def test_persona_egress(persona_id: int) -> dict:
    """Fetch Cloudflare's trace through the persona and record its exit IP."""
    async with AsyncSessionLocal() as session:
        persona = await session.get(EgressPersona, persona_id)
        if persona is None:
            raise PersonaNotFound(persona_id)
        proxy_url = persona.proxy_url

    async with httpx.AsyncClient(proxy=proxy_url, timeout=10, trust_env=False) as client:
        resp = await client.get(TRACE_URL)
        resp.raise_for_status()
    fields = dict(line.split("=", 1) for line in resp.text.splitlines() if "=" in line)
    ip = fields.get("ip")

    async with AsyncSessionLocal() as session:
        persona = await session.get(EgressPersona, persona_id)
        if persona is None:
            raise PersonaNotFound(persona_id)
        persona.last_exit_ip = ip
        persona.last_tested_at = datetime.now(UTC)
        await session.commit()
        others = list(
            (
                await session.execute(
                    select(EgressPersona).where(EgressPersona.id != persona_id, EgressPersona.last_exit_ip.is_not(None))
                )
            ).scalars()
        )
    same_ip = [o.name for o in others if ip and o.last_exit_ip == ip]
    same_subnet = [o.name for o in others if ip and o.last_exit_ip != ip and _same_subnet(ip, o.last_exit_ip)]
    return {"ip": ip, "colo": fields.get("colo"), "same_ip": same_ip, "same_subnet": same_subnet}
