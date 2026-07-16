"""Per-gallery authorization for path-addressed media URIs (F6/BR-006).

Closes audit #67/#68. nginx forwards the original request URI via
``X-Original-URI`` to the ``/api/auth/check`` auth_request subrequest;
``routers/auth.py`` delegates the URI-aware decision to this module so the
visibility rules stay defined in exactly one place (``core.auth.gallery_access_filter``).

All private media prefixes need URI-scoped authorization in addition to pure
session validation. The two path-addressed forms are:

- ``/media/libraries/<path>`` — served straight from the external library
  root (``/mnt``). Without this check, any authenticated user could browse
  *any* registered (or even unregistered — see #68) file under ``/mnt``.
- ``/media/image/insecure/...<b64>.<ext>`` — imgproxy source URL, base64
  encoded in the last path segment. imgproxy's filesystem root is the whole
  ``/data`` directory, so an unvalidated source could read arbitrary files
  (e.g. database backups) — see #67.

Content-addressed media is resolved back to ``Image`` / ``Gallery`` rows and
must have at least one accessible gallery reference. SHA256 remains the storage
identity, but possession of a URL is no longer treated as authorization.

Fail-closed: any internal error (DB, Redis, decode) returns False rather than
raising, so a bug here can only ever deny access, never leak it.
"""

from __future__ import annotations

import base64
import binascii
import logging
from urllib.parse import unquote

from sqlalchemy import select

from core.auth import gallery_access_filter
from core.database import async_session
from db.models import Blob, Gallery, Image

logger = logging.getLogger(__name__)

_LIBRARIES_PREFIX = "/media/libraries/"
_IMAGE_PREFIX = "/media/image/"
_CAS_PREFIX = "/media/cas/"
_THUMBS_PREFIX = "/media/thumbs/"
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
            return await _authorize_image(auth, uri)
        if uri.startswith(_CAS_PREFIX):
            return await _authorize_content_sha(auth, _sha_from_cas_path(uri), uri)
        if uri.startswith(_THUMBS_PREFIX):
            return await _authorize_content_sha(auth, _sha_from_thumb_path(uri), uri)
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

    async with async_session() as session:
        stmt = (
            select(Gallery.id)
            .join(Image, Image.gallery_id == Gallery.id)
            .join(Blob, Blob.sha256 == Image.blob_sha256)
            .where(Blob.external_path == mnt_path, gallery_access_filter(auth))
            .limit(1)
        )
        allowed = (await session.execute(stmt)).first() is not None

    return allowed


async def _authorize_content_sha(auth: dict, sha256: str | None, uri: str) -> bool:
    """Authorize content-addressed media through an accessible gallery reference."""
    if not sha256:
        return False
    if auth.get("role") == "admin":
        return True

    async with async_session() as session:
        stmt = (
            select(Gallery.id)
            .join(Image, Image.gallery_id == Gallery.id)
            .where(Image.blob_sha256 == sha256, gallery_access_filter(auth))
            .limit(1)
        )
        allowed = (await session.execute(stmt)).first() is not None
    return allowed


def _sha_from_cas_path(uri: str) -> str | None:
    filename = uri.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]
    return filename.rsplit(".", 1)[0] if "." in filename else None


def _sha_from_thumb_path(uri: str) -> str | None:
    parts = uri.split("?", 1)[0].strip("/").split("/")
    return parts[-2] if len(parts) >= 2 else None


async def _authorize_image(auth: dict, uri: str) -> bool:
    """Authorize a ``/media/image/...`` imgproxy request by its decoded source.

    The source prefix is constrained to CAS/thumbs, then the embedded SHA is
    checked through the same Gallery ACL path as direct content URLs.
    """
    path = uri.split("?", 1)[0]
    last_segment = path.rstrip("/").rsplit("/", 1)[-1]
    stem = last_segment.rsplit(".", 1)[0] if "." in last_segment else last_segment
    padded = stem + "=" * (-len(stem) % 4)
    try:
        decoded = base64.urlsafe_b64decode(padded).decode("utf-8")
    except binascii.Error, UnicodeDecodeError, ValueError:
        return False
    if not decoded.startswith(_ALLOWED_IMGPROXY_SOURCE_PREFIXES):
        return False
    if decoded.startswith("local:///cas/"):
        sha256 = _sha_from_cas_path(decoded.removeprefix("local://"))
    else:
        sha256 = _sha_from_thumb_path(decoded.removeprefix("local://"))
    return await _authorize_content_sha(auth, sha256, uri)
