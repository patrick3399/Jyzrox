"""Gallery identity derived from the download URL (ADR 0016).

gallery-dl already knows how every supported site's URLs are shaped, so its own
offline URL matcher decides what a URL *is* (an account, one post, a search).
The gallery is then keyed by that, never by guessing a path segment and never
by per-file metadata.
"""

import hashlib
import logging
import re
from dataclasses import dataclass

from plugins.builtin.gallery_dl._sites import _DEFAULT_CONFIG, get_site_config

logger = logging.getLogger(__name__)

_MAX_SOURCE_ID_LEN = 120
# Characters Windows rejects in names; the library tree is exported over SMB.
_WINDOWS_ILLEGAL_RE = re.compile(r'[<>:"\\|?*\x00-\x1f]')


@dataclass(frozen=True, slots=True)
class UrlIdentity:
    source: str
    source_id: str
    is_account: bool
    category: str  # raw gallery-dl category, for site config lookups


def _match_url(url: str) -> tuple[str, str, tuple[str | None, ...]] | None:
    """Return (category, subcategory, match groups) from gallery-dl, offline."""
    try:
        from gallery_dl import extractor

        extr = extractor.find(url)
    except Exception as exc:  # gallery-dl missing or its API moved
        logger.warning("[gdl_identity] cannot match %s: %s", url, exc)
        return None
    if extr is None:
        return None
    return extr.category, extr.subcategory, tuple(getattr(extr, "groups", None) or ())


def _digest(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]


def _folder_safe(source_id: str) -> str:
    """Drop what Windows cannot show; a digest of the original keeps it unique."""
    safe = _WINDOWS_ILLEGAL_RE.sub("_", source_id).rstrip(". ")
    return safe if safe == source_id else f"{safe}~{_digest(source_id)}"


def _bounded(source_id: str) -> str:
    if len(source_id) <= _MAX_SOURCE_ID_LEN:
        return source_id
    return f"{source_id[: _MAX_SOURCE_ID_LEN - 13]}~{_digest(source_id)}"


def resolve_url_identity(url: str) -> UrlIdentity | None:
    """Map a download URL to the gallery it belongs to, or None if unparseable."""
    match = _match_url(url)
    if match is None:
        return None
    category, subcategory, groups = match
    cfg = get_site_config(category)
    source = category if cfg is _DEFAULT_CONFIG else cfg.source_id

    if subcategory in cfg.account_subcategories and len(groups) > cfg.account_group:
        account = groups[cfg.account_group]
        if account:
            return UrlIdentity(source, _bounded(account), True, category)

    parts = "/".join(g for g in groups if g)
    # "=" rather than ":" — Windows rejects colons in names.
    source_id = f"{subcategory}={parts}" if parts else subcategory
    return UrlIdentity(source, _bounded(_folder_safe(source_id)), False, category)
