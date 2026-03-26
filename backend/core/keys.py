"""Derived cryptographic keys — one per domain, all from the same master key.

Each domain uses HKDF-SHA256 with a unique `info` parameter to derive an
independent 32-byte key from `settings.credential_encrypt_key`.  This
ensures key separation: compromising one derived key does not affect others.
"""

from functools import lru_cache

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from core.config import settings

_SALT = b"jyzrox-v1"


def _derive(info: bytes) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_SALT,
        info=info,
    ).derive(settings.credential_encrypt_key.encode())


@lru_cache(maxsize=1)
def credential_aes_key() -> bytes:
    """AES-256-GCM key for encrypting stored credentials."""
    return _derive(b"credential-encryption")


@lru_cache(maxsize=1)
def session_hmac_key() -> bytes:
    """HMAC-SHA256 key for signing session metadata in Redis."""
    return _derive(b"session-signing")


@lru_cache(maxsize=1)
def cursor_hmac_key() -> bytes:
    """HMAC-SHA256 key for signing pagination cursors."""
    return _derive(b"cursor-signing")
