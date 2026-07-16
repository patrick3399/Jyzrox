"""Per-gallery authorization for path-addressed media URIs (F6/BR-006).

Closes audit #67/#68. nginx forwards the original request URI via
``X-Original-URI`` to the ``/api/auth/check`` auth_request subrequest;
``routers/auth.py`` delegates the URI-aware decision to this module so the
visibility rules stay defined in exactly one place (``core.auth.gallery_access_filter``).

Two media prefixes are "path-addressed" (i.e. the URI itself names a
filesystem path rather than an opaque content-addressed hash) and therefore
need per-request authorization instead of pure session validation:

- ``/media/libraries/<path>`` — served straight from the external library
  root (``/mnt``). Without this check, any authenticated user could browse
  *any* registered (or even unregistered — see #68) file under ``/mnt``.
- ``/media/image/insecure/...<b64>.<ext>`` — imgproxy source URL, base64
  encoded in the last path segment. imgproxy's filesystem root is the whole
  ``/data`` directory, so an unvalidated source could read arbitrary files
  (e.g. database backups) — see #67.

Content-addressed media (``local:///cas/...``, ``local:///thumbs/...`` and
plain ``/media/cas/`` or ``/media/thumbs/`` URLs) is intentionally NOT
gallery-ACL-checked here: those are high-entropy sha256 capability URLs that
are only ever handed out through already-ACL-filtered API responses, and the
revocation window is bounded (see F2). That capability-URL posture is
deliberate and documented, not an oversight.

Fail-closed: any internal error (DB, Redis, decode) returns False rather than
raising, so a bug here can only ever deny access, never leak it.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import logging
from urllib.parse import unquote

from sqlalchemy import select

from core.auth import gallery_access_filter
from core.database import async_session
from core.redis_client import get_redis
from db.models import Blob, Gallery, Image

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 60
_LIBRARIES_PREFIX = "/media/libraries/"
_IMAGE_PREFIX = "/media/image/"
_ALLOWED_IMGPROXY_SOURCE_PREFIXES = ("local:///cas/", "local:///thumbs/")


async def authorize_media_uri(auth: dict, uri: str) -> bool:
    """Return whether ``auth`` may access the resource named by ``uri``.

    ``uri`` is the nginx-forwarded ``X-Original-URI`` of the request under
    evaluation. Any URI that isn't one of the managed path-addressed prefixes
    is left to the existing session-only gate and is authorized here
    unconditionally (returns True).
    """
    try:
        if uri.startswith(_LIBRARIES_PREFIX):
            return await _authorize_libraries(auth, uri)
        if uri.startswith(_IMAGE_PREFIX):
            return _authorize_image(uri)
        return True
    except Exception:
        logger.warning("authorize_media_uri: fail-closed error for uri=%r", uri, exc_info=True)
        return False


async def _authorize_libraries(auth: dict, uri: str) -> bool:
    """Authorize a ``/media/libraries/<path>`` request against gallery ACLs."""
    if auth.get("role") == "admin":
        return True

    raw_path = uri[len(_LIBRARIES_PREFIX) :].split("?", 1)[0]
    path = unquote(raw_path)
    if ".." in path.split("/"):
        return False
    mnt_path = f"/mnt/{path}"

    user_id = auth["user_id"]
    cache_key = f"mediaauthz:{user_id}:{hashlib.sha1(uri.encode()).hexdigest()}"
    redis = get_redis()
    cached = await redis.get(cache_key)
    if cached is not None:
        value = cached if isinstance(cached, str) else cached.decode()
        return value == "1"

    async with async_session() as session:
        stmt = (
            select(Gallery.id)
            .join(Image, Image.gallery_id == Gallery.id)
            .join(Blob, Blob.sha256 == Image.blob_sha256)
            .where(Blob.external_path == mnt_path, gallery_access_filter(auth))
            .limit(1)
        )
        allowed = (await session.execute(stmt)).first() is not None

    await redis.set(cache_key, "1" if allowed else "0", ex=_CACHE_TTL_SECONDS)
    return allowed


def _authorize_image(uri: str) -> bool:
    """Authorize a ``/media/image/...`` imgproxy request by its decoded source.

    Does not consult gallery ACLs — the underlying resource is itself a
    capability URL (see module docstring); only the source prefix is
    validated so imgproxy cannot be used to read files outside CAS/thumbs.
    """
    path = uri.split("?", 1)[0]
    last_segment = path.rstrip("/").rsplit("/", 1)[-1]
    stem = last_segment.rsplit(".", 1)[0] if "." in last_segment else last_segment
    padded = stem + "=" * (-len(stem) % 4)
    try:
        decoded = base64.urlsafe_b64decode(padded).decode("utf-8")
    except binascii.Error, UnicodeDecodeError, ValueError:
        return False
    return decoded.startswith(_ALLOWED_IMGPROXY_SOURCE_PREFIXES)
