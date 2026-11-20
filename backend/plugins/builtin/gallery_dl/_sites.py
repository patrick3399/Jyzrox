"""Unified gallery-dl site configuration registry.

Single source of truth for all gallery-dl supported sites.
Replaces scattered config in source.py, _subscribe.py, _metadata.py, and importer.py.
"""

import re
import types
import typing
from collections.abc import Iterable, Mapping
from dataclasses import fields
from typing import Literal

from ._site_config import GdlSiteConfig
from ._sites_data_booru_art import SITES_BOORU_ART
from ._sites_data_gallery import SITES_GALLERY_FILEHOST
from ._sites_data_social import SITES_EH_SOCIAL

GDL_SITES: tuple[GdlSiteConfig, ...] = (*SITES_EH_SOCIAL, *SITES_BOORU_ART, *SITES_GALLERY_FILEHOST)

# ── Lookup helpers ──

_BY_SOURCE: dict[str, GdlSiteConfig] = {}
_BY_DOMAIN: dict[str, GdlSiteConfig] = {}
for _s in GDL_SITES:
    _BY_SOURCE.setdefault(_s.source_id, _s)  # first entry wins (e-hentai.org before exhentai.org)
    _BY_DOMAIN[_s.domain] = _s

_DEFAULT_CONFIG = GdlSiteConfig(
    domain="",
    source_id="gallery_dl",
    name="Unknown Site",
    category="other",
)

_ALIASES: dict[str, str] = {"exhentai": "ehentai"}


# ── Sites declared by drop-in extractors (JYZROX_SITE) ──
#
# A custom extractor module under extractors/ may carry a module-level
# ``JYZROX_SITE`` dict (or a list of them); ``_extractors.load_inprocess()``
# validates it here and registers it next to GDL_SITES. Static entries win.

_EXTRA_SITES: list[GdlSiteConfig] = []
_EXTRA_METADATA_FIELDS: list[str] = []

# Group names the site list uses; "other" is what an unregistered site shows as.
_SITE_CATEGORIES = frozenset(s.category for s in GDL_SITES) | {"other"}
# Not declarable: the toggles name a Settings attribute and the warning code a
# frontend i18n key, neither of which a drop-in file can add. ``extractor`` is
# the extractor's own category: source_id must already be that category, or
# get_site_config(category) would miss the entry.
_UNDECLARABLE = frozenset({"extractor", "feature_toggle_key", "feature_toggle_attr", "credential_warning_code"})
_DECLARABLE = frozenset(f.name for f in fields(GdlSiteConfig)) - _UNDECLARABLE
_FIELD_TYPES = typing.get_type_hints(GdlSiteConfig)
_SOURCE_ID_RE = re.compile(r"[a-z0-9][a-z0-9_-]*")
_DOMAIN_RE = re.compile(r"(?:[a-z0-9-]+\.)+[a-z0-9-]+")
_FIELD_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class SiteDeclarationError(ValueError):
    """A JYZROX_SITE declaration that cannot become a GdlSiteConfig."""


def _coerce(name: str, hint, value):
    """Check ``value`` against a GdlSiteConfig annotation; lists become tuples."""
    origin, args = typing.get_origin(hint), typing.get_args(hint)
    if origin is Literal:
        if value in args:
            return value
        raise SiteDeclarationError(f"{name} must be one of {', '.join(map(repr, args))}, not {value!r}")
    if origin in (typing.Union, types.UnionType):
        for arg in args:
            try:
                return _coerce(name, arg, value)
            except SiteDeclarationError:
                continue
        raise SiteDeclarationError(f"{name} has an invalid value: {value!r}")
    if origin is tuple:
        if not isinstance(value, (list, tuple)):
            raise SiteDeclarationError(f"{name} must be a list or tuple, not {type(value).__name__}")
        if len(args) == 2 and args[1] is Ellipsis:
            return tuple(_coerce(name, args[0], item) for item in value)
        if len(value) != len(args):
            raise SiteDeclarationError(f"{name} must have {len(args)} items")
        return tuple(_coerce(name, arg, item) for arg, item in zip(args, value, strict=True))
    if hint is type(None):
        if value is None:
            return None
    elif hint is float:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    elif hint is int:
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    elif isinstance(value, hint):
        return value
    raise SiteDeclarationError(f"{name} has an invalid value: {value!r}")


def site_config_from_declaration(
    declaration: object, extractor_categories: Iterable[str]
) -> tuple[GdlSiteConfig, tuple[str, ...]]:
    """Validate one JYZROX_SITE dict; return the site and its metadata fields.

    ``source_id`` defaults to the module's extractor category and must be one
    of them. The metadata fields are the ``metadata_include`` names plus the
    top-level key of every title/artist/source_id field path, because the
    metadata postprocessor drops whatever ``_METADATA_INCLUDE`` does not list.
    """
    if not isinstance(declaration, Mapping):
        raise SiteDeclarationError(f"must be a dict, not {type(declaration).__name__}")
    values = dict(declaration)
    categories = sorted(set(extractor_categories))

    metadata_include = values.pop("metadata_include", ())
    unknown = sorted(set(values) - _DECLARABLE)
    if unknown:
        raise SiteDeclarationError(f"unsupported keys: {', '.join(unknown)}")
    missing = sorted({"domain", "name", "category"} - set(values))
    if missing:
        raise SiteDeclarationError(f"missing required keys: {', '.join(missing)}")
    if "source_id" not in values:
        if len(categories) != 1:
            raise SiteDeclarationError(f"source_id is required when the module has categories {categories}")
        values["source_id"] = categories[0]

    values = {key: _coerce(key, _FIELD_TYPES[key], value) for key, value in values.items()}
    if values["source_id"] not in categories:
        raise SiteDeclarationError(f"source_id {values['source_id']!r} is not an extractor category of the module")
    if not _SOURCE_ID_RE.fullmatch(values["source_id"]) or values["source_id"] == _DEFAULT_CONFIG.source_id:
        raise SiteDeclarationError(f"source_id {values['source_id']!r} is not usable")
    values["domain"] = values["domain"].strip().lower().removeprefix("www.")
    if not _DOMAIN_RE.fullmatch(values["domain"]):
        raise SiteDeclarationError(f"domain {values['domain']!r} must be a bare host name like example.com")
    if values["category"] not in _SITE_CATEGORIES:
        raise SiteDeclarationError(f"category must be one of {', '.join(sorted(_SITE_CATEGORIES))}")

    metadata_include = _coerce("metadata_include", tuple[str, ...], metadata_include)
    config = GdlSiteConfig(**values)
    paths = (*config.title_fields, *config.artist_fields, *config.source_id_fields)
    metadata_fields = tuple(dict.fromkeys([*metadata_include, *(path.split(".", 1)[0] for path in paths)]))
    bad = [name for name in metadata_fields if not _FIELD_NAME_RE.fullmatch(name)]
    if bad:
        raise SiteDeclarationError(f"invalid metadata field names: {', '.join(bad)}")
    return config, metadata_fields


def register_site(config: GdlSiteConfig, metadata_fields: Iterable[str] = ()) -> str | None:
    """Add a drop-in extractor's site; returns why it was ignored, or None.

    A source_id or domain already taken — by GDL_SITES or an earlier
    declaration — keeps its owner, so a stray file cannot redefine a built-in site.
    """
    if config.source_id in _BY_SOURCE or config.source_id in _ALIASES:
        return f"source_id {config.source_id!r} is already registered"
    if config.domain in _BY_DOMAIN:
        return f"domain {config.domain!r} is already registered to {_BY_DOMAIN[config.domain].source_id!r}"
    _EXTRA_SITES.append(config)
    _BY_SOURCE[config.source_id] = config
    _BY_DOMAIN[config.domain] = config
    for name in metadata_fields:
        if name not in _EXTRA_METADATA_FIELDS:
            _EXTRA_METADATA_FIELDS.append(name)
    return None


def all_sites() -> tuple[GdlSiteConfig, ...]:
    """GDL_SITES followed by the sites drop-in extractors declared."""
    return (*GDL_SITES, *_EXTRA_SITES)


def extra_metadata_fields() -> tuple[str, ...]:
    """Metadata fields drop-in extractors need kept by the metadata postprocessor."""
    return tuple(_EXTRA_METADATA_FIELDS)


def get_site_config(source: str) -> GdlSiteConfig:
    """Look up site config by source_id. Unknown sites → _DEFAULT_CONFIG."""
    resolved = _ALIASES.get(source, source)
    return _BY_SOURCE.get(resolved, _DEFAULT_CONFIG)


def gdl_extractor_name(source: str) -> str:
    """gallery-dl category whose config section and archive table belong to ``source``.

    A source outside GDL_SITES is already a raw gallery-dl category, so it names
    itself. Going through ``_DEFAULT_CONFIG`` instead would file its credentials
    and archive rows under "gallery_dl", which gallery-dl never reads.
    """
    cfg = get_site_config(source)
    if cfg is _DEFAULT_CONFIG:
        return source
    return cfg.extractor or cfg.source_id


def get_site_by_domain(domain: str) -> GdlSiteConfig:
    """Look up site config by domain. Unknown domains → _DEFAULT_CONFIG."""
    return _BY_DOMAIN.get(domain, _DEFAULT_CONFIG)


def cookie_writeback_path(job_id: str, source: str) -> str:
    """Path gallery-dl exports refreshed cookies to (cookies-update) and the
    worker's _writeback_cookies() reads back. Single source of truth — the
    config writer and the worker reader must never drift apart.
    """
    return f"/tmp/gdl-cookies-{job_id}-{source}.txt"
