"""Egress personas: fixed (proxy, account, browser identity) bundles for gallery-dl jobs (ADR 0022).

A persona job never borrows the active account: it either brings the account
bound to it for that site or runs anonymously, and it never changes persona
mid-run. Admission stays the Postgres FIFO; the Redis cooldown only removes
candidates and fails open.
"""

from __future__ import annotations

import ipaddress
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import AsyncSessionLocal
from core.redis_client import get_redis
from db.models import Credential, DownloadJob, EgressPersona, PersonaAccount
from services.credential import get_account_credential
from services.download_admission import (
    AdmissionClaim,
    DownloadAdmission,
    PersonaSlot,
    admission_key_for,
    persona_admission_key,
)

logger = logging.getLogger(__name__)

PERSONA_COOLDOWN_SECONDS = 1800
TRACE_URL = "https://www.cloudflare.com/cdn-cgi/trace"
# 403 first: a block outlives a rate limit, so it names the cooldown reason.
_SIGNAL_ORDER = ("http_403", "http_429")


def cooldown_key(persona_id: int, source_id: str) -> str:
    return f"persona:cooldown:{persona_id}:{source_id}"


async def resolve_admission_key(source: str | None, url: str, *, subscription_id: int | None) -> str:
    """Return the admission key to persist on a download row (ADR 0022).

    Persona mode is decided when the row is written, never at claim time: the
    final queue key must be stored before delivery so every older row is
    already in the FIFO it will be claimed from. Only manual (non-subscription)
    gallery-dl jobs on a site with ``spread_personas`` queue on ``{key}#persona``.
    """
    base = admission_key_for(source, url)
    if not base.startswith("gallery_dl:") or subscription_id is not None:
        return base

    from core.site_config import site_config_service
    from plugins.builtin.gallery_dl._sites import get_site_by_domain

    domain = (urlparse(url).hostname or "unknown").removeprefix("www.")
    site_source_id = get_site_by_domain(domain).source_id
    try:
        params = await site_config_service.get_effective_download_params(site_source_id)
    except Exception as exc:  # a config read failure must not block job creation: fall back to the site queue
        logger.warning("[persona] site config lookup failed for %s, using the site queue: %s", site_source_id, exc)
        return base
    return persona_admission_key(base) if params.spread_personas else base


# ── Admission ─────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class SlotDecision:
    claim: AdmissionClaim
    key: str
    personas_cooling: bool  # every eligible persona is cooling for this site
    persona_mode: bool  # the persona claim path was taken (False on the legacy path, incl. no-eligible fallback)


async def _cooling_ids(persona_ids: list[int], source_id: str) -> set[int]:
    if not persona_ids:
        return set()
    try:
        values = await get_redis().mget([cooldown_key(pid, source_id) for pid in persona_ids])
    except Exception as exc:  # RedisError, or RuntimeError when Redis is not initialised: fail open
        logger.warning("[persona] cooldown lookup failed, treating none as cooling: %s", exc)
        return set()
    return {pid for pid, value in zip(persona_ids, values, strict=True) if value is not None}


async def _eligible_personas(session: AsyncSession, source_id: str) -> list[EgressPersona]:
    personas = list(
        (await session.execute(select(EgressPersona).where(EgressPersona.enabled).order_by(EgressPersona.id))).scalars()
    )
    if not personas:
        return []
    site_accounts = (
        await session.execute(select(func.count()).select_from(Credential).where(Credential.source == source_id))
    ).scalar_one()
    if not site_accounts:
        return personas
    bound = set(
        (await session.execute(select(PersonaAccount.persona_id).where(PersonaAccount.source == source_id))).scalars()
    )
    return [p for p in personas if p.id in bound]


async def _preferred_persona_id(session: AsyncSession, job_uuid: uuid.UUID) -> int | None:
    # Column selects only: loading the DownloadJob entity here would leave a
    # stale object in the identity map for the claim's SELECT ... FOR UPDATE.
    row = (
        await session.execute(
            select(DownloadJob.persona_id, DownloadJob.canonical_url).where(DownloadJob.id == job_uuid)
        )
    ).one_or_none()
    if row is None:
        return None
    if row.persona_id is not None:
        return row.persona_id
    if not row.canonical_url:
        return None
    return (
        await session.execute(
            select(DownloadJob.persona_id)
            .where(
                DownloadJob.canonical_url == row.canonical_url,
                DownloadJob.persona_id.is_not(None),
                DownloadJob.id != job_uuid,
            )
            .order_by(DownloadJob.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


def _as_uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


async def claim_download_slot(
    session: AsyncSession,
    *,
    job_id: str,
    base_key: str,
    site_source_id: str,
    capacity: int,
    admission: DownloadAdmission | None = None,
) -> SlotDecision:
    """Claim admission, spreading over personas when the row was stamped for it.

    Persona mode is read from the row's stored ``admission_key`` (written by
    ``resolve_admission_key``), not from the live site switch. With no eligible
    persona the job falls back to today's direct path.
    ``admission`` lets the caller supply the DownloadAdmission it already owns.
    """
    if admission is None:
        admission = DownloadAdmission(session)
    persona_key = persona_admission_key(base_key)
    stored_key = None
    job_uuid = _as_uuid(job_id)
    # Only gallery-dl rows are ever stamped with a persona key.
    if job_uuid is not None and base_key.startswith("gallery_dl:"):
        # Column-only select: loading the DownloadJob entity before the claim's
        # SELECT ... FOR UPDATE would leave a stale object in the identity map.
        stored_key = (
            await session.execute(select(DownloadJob.admission_key).where(DownloadJob.id == job_uuid))
        ).scalar_one_or_none()
    if stored_key == persona_key:
        eligible = await _eligible_personas(session, site_source_id)
        if eligible:
            cooling = await _cooling_ids([p.id for p in eligible], site_source_id)
            slots = [
                PersonaSlot(persona_id=p.id, name=p.name, capacity=max(1, int(capacity)))
                for p in eligible
                if p.id not in cooling
            ]
            preferred = await _preferred_persona_id(session, job_uuid)
            claim = await admission.claim_with_personas(job_id, persona_key, slots, preferred)
            return SlotDecision(claim=claim, key=persona_key, personas_cooling=not slots, persona_mode=True)
    claim = await admission.claim(job_id, base_key, capacity)
    return SlotDecision(claim=claim, key=base_key, personas_cooling=False, persona_mode=False)


# ── Run-time identity ─────────────────────────────────────────────────


class PersonaUnavailable(Exception):
    """The persona or its bound credential disappeared after the claim."""


@dataclass(frozen=True, slots=True)
class PersonaIdentity:
    persona_id: int
    name: str
    proxy_url: str | None
    user_agent: str | None
    browser_profile: str | None
    account: str | None  # bound account for the job's site; None = anonymous

    def network_options(self) -> dict:
        return {"proxy_url": self.proxy_url, "user_agent": self.user_agent, "browser_profile": self.browser_profile}


async def _load_identity(persona_id: int, source_id: str) -> PersonaIdentity | None:
    async with AsyncSessionLocal() as session:
        persona = await session.get(EgressPersona, persona_id)
        if persona is None:
            return None
        account = (
            await session.execute(
                select(PersonaAccount.account).where(
                    PersonaAccount.persona_id == persona_id, PersonaAccount.source == source_id
                )
            )
        ).scalar_one_or_none()
        return PersonaIdentity(
            persona.id, persona.name, persona.proxy_url, persona.user_agent, persona.browser_profile, account
        )


async def prepare_persona_run(
    persona_id: int, source_id: str, credentials: dict | None, accounts: dict[str, str]
) -> tuple[PersonaIdentity, dict, dict[str, str]]:
    """Return the persona identity plus credentials with the site's account swapped in.

    A persona without a binding for the site runs anonymously: the active
    account is removed, never borrowed.
    """
    identity = await _load_identity(persona_id, source_id)
    if identity is None:
        raise PersonaUnavailable(f"Egress persona {persona_id} no longer exists")
    creds = dict(credentials or {})
    accts = dict(accounts or {})
    if identity.account is None:
        creds.pop(source_id, None)
        accts.pop(source_id, None)
        return identity, creds, accts
    bound = await get_account_credential(source_id, identity.account)
    if bound is None:
        raise PersonaUnavailable(
            f"Persona {identity.name}: credential {source_id}/{identity.account} is missing or expired"
        )
    creds[source_id] = bound.value
    accts[source_id] = bound.account
    return identity, creds, accts


def throttle_signal(diagnostic_ctx: dict) -> str | None:
    seen = set(diagnostic_ctx.get("throttle_signals") or ())
    return next((s for s in _SIGNAL_ORDER if s in seen), None)


async def mark_persona_cooldown(persona_id: int, source_id: str, reason: str) -> None:
    try:
        await get_redis().set(cooldown_key(persona_id, source_id), reason, ex=PERSONA_COOLDOWN_SECONDS)
        logger.warning("[persona] %s cooling for %s (%s)", persona_id, source_id, reason)
    except Exception as exc:  # never let a cooldown write change the job's outcome
        logger.warning("[persona] failed to set cooldown for %s/%s: %s", persona_id, source_id, exc)


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
