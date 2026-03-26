"""AES-256-GCM credential encryption + DB persistence."""

import os
from datetime import UTC, datetime

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from core.database import AsyncSessionLocal
from core.keys import credential_aes_key
from db.models import Credential


def encrypt(plaintext: str) -> bytes:
    """Encrypt with AES-256-GCM. Returns nonce(12 bytes) + ciphertext."""
    nonce = os.urandom(12)
    ct = AESGCM(credential_aes_key()).encrypt(nonce, plaintext.encode(), None)
    return nonce + ct


def decrypt(data: bytes) -> str:
    """Decrypt AES-256-GCM. Input must be nonce(12) + ciphertext."""
    nonce, ct = data[:12], data[12:]
    return AESGCM(credential_aes_key()).decrypt(nonce, ct, None).decode()


async def get_credential(source: str) -> str | None:
    """Load and decrypt a credential by source name. Returns None if not set or expired."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Credential).where(Credential.source == source))
        cred = result.scalar_one_or_none()
        if cred is None or cred.value_encrypted is None:
            return None
        if cred.expires_at is not None:
            # Normalise to offset-aware UTC for comparison
            expires = cred.expires_at
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=UTC)
            if expires < datetime.now(UTC):
                return None
        return decrypt(bytes(cred.value_encrypted))


async def set_credential(source: str, value: str, cred_type: str) -> None:
    """Encrypt and upsert a credential."""
    encrypted = encrypt(value)
    async with AsyncSessionLocal() as session:
        stmt = (
            pg_insert(Credential)
            .values(source=source, credential_type=cred_type, value_encrypted=encrypted)
            .on_conflict_do_update(
                index_elements=["source"],
                set_={"credential_type": cred_type, "value_encrypted": encrypted},
            )
        )
        await session.execute(stmt)
        await session.commit()


async def list_credentials() -> list[dict]:
    """Return all credential sources with their configured status (values never exposed)."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Credential))
        return [
            {"source": c.source, "credential_type": c.credential_type, "configured": True}
            for c in result.scalars().all()
        ]
