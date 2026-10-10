"""AES-256-GCM credential encryption + DB persistence.

A source can hold several accounts; exactly one of them is active. A reader
that asks for "the credential of a source" gets the active account (ADR 0019).
"""

import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import select, update

from core.database import AsyncSessionLocal, advisory_xact_lock
from core.keys import credential_aes_key
from db.models import Credential

DEFAULT_ACCOUNT = "default"
ACCOUNT_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._@-]{0,39}$"
_ACCOUNT_RE = re.compile(ACCOUNT_PATTERN)

# Serializes every "read the accounts of a source, then write" sequence; without
# it two concurrent first saves both see "no active account yet". Distinct from
# routers/users.py (771_007) and routers/auth.py (771_008).
_CREDENTIAL_LOCK_KEY = 771_030


@dataclass(frozen=True, slots=True)
class ActiveCredential:
    """A decrypted credential together with the account it was read from."""

    account: str
    value: str


def encrypt(plaintext: str) -> bytes:
    """Encrypt with AES-256-GCM. Returns nonce(12 bytes) + ciphertext."""
    nonce = os.urandom(12)
    ct = AESGCM(credential_aes_key()).encrypt(nonce, plaintext.encode(), None)
    return nonce + ct


def decrypt(data: bytes) -> str:
    """Decrypt AES-256-GCM. Input must be nonce(12) + ciphertext."""
    nonce, ct = data[:12], data[12:]
    return AESGCM(credential_aes_key()).decrypt(nonce, ct, None).decode()


def normalize_account(account: str) -> str:
    """Return the trimmed account name; raise ValueError when it is not a valid name."""
    name = account.strip()
    if not _ACCOUNT_RE.fullmatch(name):
        raise ValueError(
            "account must be 1-40 characters (letters, digits, '.', '_', '@', '-') and start with a letter or digit"
        )
    return name


def _is_expired(cred: Credential) -> bool:
    if cred.expires_at is None:
        return False
    # Normalise to offset-aware UTC for comparison
    expires = cred.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    return expires < datetime.now(UTC)


async def get_active_credential(source: str) -> ActiveCredential | None:
    """Load and decrypt the active account of a source. None if not set or expired."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Credential).where(Credential.source == source, Credential.is_active))
        cred = result.scalar_one_or_none()
        if cred is None or cred.value_encrypted is None or _is_expired(cred):
            return None
        return ActiveCredential(account=cred.account, value=decrypt(bytes(cred.value_encrypted)))


async def get_credential(source: str) -> str | None:
    """Load and decrypt the active credential of a source. Returns None if not set or expired."""
    active = await get_active_credential(source)
    return active.value if active else None


async def set_credential(source: str, value: str, cred_type: str, account: str | None = None) -> str:
    """Encrypt and store a credential. Returns the account it was written to.

    ``account=None`` overwrites the active account, or creates ``default`` when
    the source has none. A named account is created or overwritten in place and
    does not become active — unless the source has no active account, in which
    case whatever is written is activated so the source is never left unreadable.
    """
    encrypted = encrypt(value)
    async with AsyncSessionLocal() as session:
        await advisory_xact_lock(session, _CREDENTIAL_LOCK_KEY)
        rows = (await session.execute(select(Credential).where(Credential.source == source))).scalars().all()
        active = next((row for row in rows if row.is_active), None)
        if account is not None:
            name = normalize_account(account)
        else:
            name = active.account if active else DEFAULT_ACCOUNT
        target = next((row for row in rows if row.account == name), None)
        if target is None:
            session.add(
                Credential(
                    source=source,
                    account=name,
                    is_active=active is None,
                    credential_type=cred_type,
                    value_encrypted=encrypted,
                )
            )
        else:
            target.credential_type = cred_type
            target.value_encrypted = encrypted
            if active is None:
                target.is_active = True
        await session.commit()
        return name


async def set_credential_for_account(source: str, account: str, value: str, cred_type: str) -> bool:
    """Overwrite an existing account in place. Never creates one, never changes which is active.

    The download worker uses this to write refreshed cookies back to the account
    a job started with. False when that account was deleted in the meantime.
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            update(Credential)
            .where(Credential.source == source, Credential.account == account)
            .values(credential_type=cred_type, value_encrypted=encrypt(value))
        )
        await session.commit()
        return result.rowcount == 1


async def list_credentials() -> list[dict]:
    """Return one entry per configured source, describing its active account (values never exposed)."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Credential))
        rows = result.scalars().all()
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.source] = counts.get(row.source, 0) + 1
    return [
        {
            "source": row.source,
            "credential_type": row.credential_type,
            "configured": True,
            "account": row.account,
            "accounts": counts[row.source],
        }
        for row in rows
        if row.is_active
    ]


async def list_accounts(source: str) -> list[dict]:
    """Return every account of a source, active first then by name (values never exposed)."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Credential)
            .where(Credential.source == source)
            .order_by(Credential.is_active.desc(), Credential.account)
        )
        return [
            {"account": row.account, "credential_type": row.credential_type, "is_active": bool(row.is_active)}
            for row in result.scalars().all()
        ]


async def activate_account(source: str, account: str) -> bool:
    """Make ``account`` the active account of ``source``. False when it does not exist."""
    async with AsyncSessionLocal() as session:
        await advisory_xact_lock(session, _CREDENTIAL_LOCK_KEY)
        found = (
            await session.execute(
                select(Credential.account).where(Credential.source == source, Credential.account == account)
            )
        ).scalar_one_or_none()
        if found is None:
            await session.rollback()
            return False
        # Two statements on purpose: PostgreSQL checks a unique index row by row,
        # so a single UPDATE flipping both rows can fail on the intermediate state.
        await session.execute(
            update(Credential).where(Credential.source == source, Credential.is_active).values(is_active=False)
        )
        await session.execute(
            update(Credential).where(Credential.source == source, Credential.account == account).values(is_active=True)
        )
        await session.commit()
        return True


async def delete_account(source: str, account: str | None = None) -> str:
    """Delete one account; ``account=None`` targets the active one.

    Returns ``"deleted"``, ``"not_found"`` or ``"active_in_use"``. The active
    account cannot go while the source still has others: that would leave a
    source with accounts but nothing for readers to use.
    """
    async with AsyncSessionLocal() as session:
        await advisory_xact_lock(session, _CREDENTIAL_LOCK_KEY)
        rows = (await session.execute(select(Credential).where(Credential.source == source))).scalars().all()
        if account is None:
            # Falls back to a lone inactive row so a source left without an
            # active account (raw SQL, downgrade/upgrade) can still be cleared.
            target = next((row for row in rows if row.is_active), rows[0] if len(rows) == 1 else None)
        else:
            target = next((row for row in rows if row.account == account), None)
        if target is None:
            await session.rollback()
            return "not_found"
        if target.is_active and len(rows) > 1:
            await session.rollback()
            return "active_in_use"
        await session.delete(target)
        await session.commit()
        return "deleted"


def parse_cookie_input(raw: str) -> dict[str, str]:
    """Parse user-pasted cookie text into a name→value dict.

    Thin wrapper over the gallery-dl plugin's parser so routers do not import
    plugins.builtin internals (pre-commit gate 2 / architecture risk #2).
    """
    from plugins.builtin.gallery_dl._credentials import parse_cookie_input as _parse

    return _parse(raw)
