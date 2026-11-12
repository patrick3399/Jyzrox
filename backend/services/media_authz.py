"""Per-gallery authorization for path-addressed media URIs (F6/BR-006).

Closes audit #67/#68. nginx forwards the original request URI via
``X-Original-URI`` to the ``/api/auth/check`` auth_request subrequest;
``routers/auth.py`` delegates the URI-aware decision to this module so the
visibility rules stay defined in exactly one place (``core.auth.gallery_access_filter``).

The two path-addressed forms need URI-scoped authorization in addition to pure
session validation:

- ``/media/libraries/<path>`` — served straight from the external library
  root (``/mnt``). Without this check, any authenticated user could browse
  *any* registered (or even unregistered — see #68) file under ``/mnt``.
- ``/media/image/insecure/...<b64>.<ext>`` — imgproxy source URL, base64
  encoded after the processing options. imgproxy's filesystem root is the
  whole ``/data`` directory and it resolves ``..`` in local sources, so an
  unvalidated source could read arbitrary images under ``/data`` — see #67.
  The source is decoded the way nginx + imgproxy will see it, not from the
  raw last segment.

Content-addressed CAS/thumb URLs use authenticated-capability semantics: nginx
still requires a valid session, but the high-entropy SHA is not resolved back
through Gallery ACLs on the image hot path. This is the deliberate default for
Jyzrox's single-user-first deployment model. Path-addressed libraries retain
Gallery ACLs, and imgproxy sources are constrained to CAS/thumb storage so it
cannot expose arbitrary files under ``/data``.

Fail-closed: any internal error (DB or decode) returns False rather than
raising, so a bug here can only ever deny access, never leak it.
"""

from __future__ import annotations

import base64
import binascii
import logging
import re
from urllib.parse import unquote

from sqlalchemy import select

from core.auth import gallery_access_filter
from core.database import async_session
from db.models import Gallery, Image

logger = logging.getLogger(__name__)

_LIBRARIES_PREFIX = "/media/libraries/"
_IMAGE_PREFIX = "/media/image/"
_LOCAL_SOURCE_PREFIX = "local:///"
_ALLOWED_IMGPROXY_SOURCE_ROOTS = frozenset({"cas", "thumbs"})
_BASE64URL_RE = re.compile(r"[A-Za-z0-9_-]+")
# A leading dot is refused, which also rules out "." and ".." segments.
_SOURCE_SEGMENT_RE = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9._-]*")


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

    async with async_session() as session:
        stmt = (
            select(Gallery.id)
            .join(Image, Image.gallery_id == Gallery.id)
            .where(Image.external_path == mnt_path, gallery_access_filter(auth))
            .limit(1)
        )
        allowed = (await session.execute(stmt)).first() is not None

    return allowed


def _nginx_normalized_path(raw_path: str) -> str | None:
    """Return the path nginx proxies upstream for a raw ``$request_uri`` path.

    auth_request sees the raw URI, but nginx hands imgproxy the normalized
    ``$uri``: percent-decoded (``%2F`` becomes a separator, ``%2e%2e`` a dot
    segment), slashes merged, ``.``/``..`` resolved. Authorizing anything else
    would judge a different source than the one imgproxy loads. ``None`` when
    ``..`` climbs above the root (nginx answers 400).
    """
    decoded = unquote(raw_path, errors="strict")
    if any(ord(ch) < 0x20 or ch == "\x7f" for ch in decoded):
        return None
    segments: list[str] = []
    for segment in decoded.split("/"):
        if segment in ("", "."):
            continue
        if segment == "..":
            if not segments:
                return None
            segments.pop()
        else:
            segments.append(segment)
    return "/" + "/".join(segments)


def _imgproxy_source(path: str) -> str | None:
    """Decode the source imgproxy will load for a normalized ``/media/image/`` path.

    Mirrors imgproxy's path parsing: the first segment is the signature,
    leading ``name:args`` segments are processing options, and every remaining
    segment is joined *before* base64-decoding (imgproxy accepts a base64
    source split by ``/`` at any offset). The extension is cut at the last dot
    of the joined string. ``plain/`` and ``enc/`` sources are never emitted by
    the app and are rejected.
    """
    parts = path[len(_IMAGE_PREFIX) :].split("/")[1:]
    first_source = 0
    while first_source < len(parts) and ":" in parts[first_source]:
        first_source += 1
    source_parts = parts[first_source:]
    if not source_parts or source_parts[0] in ("plain", "enc"):
        return None
    encoded = "".join(source_parts)
    if "." in encoded:
        encoded = encoded[: encoded.rindex(".")]
    encoded = encoded.rstrip("=")
    if not _BASE64URL_RE.fullmatch(encoded):
        return None
    return base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode("utf-8")


def _source_allowed(source: str) -> bool:
    """Whether a decoded ``local:///`` source stays inside CAS/thumb storage.

    imgproxy resolves ``..`` inside local sources, so a prefix check alone lets
    ``local:///cas/../<anything>`` read any image under ``/data``. Every segment
    must be a plain name: no dot segments, empty segments, dotfiles, or
    characters (``%``, ``?``, ``#``, ``\\``, ``:``) that imgproxy might decode or
    reinterpret.
    """
    if not source.startswith(_LOCAL_SOURCE_PREFIX):
        return False
    segments = source[len(_LOCAL_SOURCE_PREFIX) :].split("/")
    return (
        len(segments) >= 2
        and segments[0] in _ALLOWED_IMGPROXY_SOURCE_ROOTS
        and all(_SOURCE_SEGMENT_RE.fullmatch(segment) for segment in segments)
    )


def _authorize_image(uri: str) -> bool:
    """Authorize a ``/media/image/...`` imgproxy request by its decoded source.

    The source is reconstructed exactly as nginx + imgproxy will see it and
    must resolve inside CAS/thumbs. Session authentication is handled by
    nginx/auth.py; no per-Gallery DB query is needed here.
    """
    path = _nginx_normalized_path(uri.split("?", 1)[0])
    if path is None or not path.startswith(_IMAGE_PREFIX):
        return False
    try:
        source = _imgproxy_source(path)
    except binascii.Error, UnicodeDecodeError, ValueError:
        return False
    return source is not None and _source_allowed(source)
