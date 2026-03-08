"""AES-256-GCM credential encryption + DB persistence."""

import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from core.config import settings
from core.database import AsyncSessionLocal
from db.models import Credential

_KEY: bytes | None = None


def _get_key() -> bytes:
    global _KEY
    if _KEY is None:
        kdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"jyzrox-v1",
            info=b"credential-encryption",
        )
        _KEY = kdf.derive(settings.credential_encrypt_key.encode())
    return _KEY


def encrypt(plaintext: str) -> bytes:
    """Encrypt with AES-256-GCM. Returns nonce(12 bytes) + ciphertext."""
    nonce = os.urandom(12)
    ct = AESGCM(_get_key()).encrypt(nonce, plaintext.encode(), None)
    return nonce + ct


def decrypt(data: bytes) -> str:
    """Decrypt AES-256-GCM. Input must be nonce(12) + ciphertext."""
    nonce, ct = data[:12], data[12:]
    return AESGCM(_get_key()).decrypt(nonce, ct, None).decode()


async def get_credential(source: str) -> str | None:
    """Load and decrypt a credential by source name. Returns None if not set."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Credential).where(Credential.source == source))
        cred = result.scalar_one_or_none()
        if cred is None or cred.value_encrypted is None:
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
