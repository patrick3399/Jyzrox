"""Pure planning logic for the one-off local gallery category migration.

Stdlib only, by contract: this module is imported both inside the backend
image and directly by the host interpreter (the source tree lives on a
host-owned, container-read-only bind mount, so the directory rename half of
the migration cannot run in a container). Importing settings, models or
services here would break the host half.

``safe_source_id`` is duplicated from ``services.cas`` for that reason. The
copy is pinned by an equivalence regression test
(``test_safe_source_id_matches_cas_implementation_for_representative_ids``).
"""

from __future__ import annotations

_MAX_CATEGORY_LEN = 64
_EXPECTED_SEGMENTS = 3


class MigrationError(Exception):
    """Raised for any state the migration refuses to act on."""


def safe_source_id(source_id: str) -> str:
    """Mirror of services.cas.safe_source_id — keep the two in lockstep."""
    return source_id.strip().replace("/", "__").replace("..", "_")


def load_mapping(path: str) -> dict[str, str]:
    """Read an artist->category TSV. Only the first two columns are used."""
    mapping: dict[str, str] = {}
    with open(path, encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, start=1):
            line = raw.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            parts = line.split("\t")
            artist = parts[0].strip()
            category = parts[1].strip() if len(parts) > 1 else ""
            if not artist:
                raise MigrationError(f"line {lineno}: empty artist")
            if not category:
                raise MigrationError(f"line {lineno}: empty category for artist {artist!r}")
            if artist in mapping:
                raise MigrationError(f"line {lineno}: duplicate artist {artist!r}")
            mapping[artist] = category
    if not mapping:
        raise MigrationError("mapping file contains no rows")
    return mapping


def validate_mapping(mapping: dict[str, str], artists: set[str]) -> None:
    """Refuse anything that could produce an unsafe or partial migration."""
    for artist, category in sorted(mapping.items()):
        if artist not in artists:
            raise MigrationError(f"unknown artist in mapping: {artist!r}")
        _validate_category_name(category)
    missing = sorted(artists - set(mapping))
    if missing:
        raise MigrationError(f"artists not covered by mapping: {missing}")


def _validate_category_name(category: str) -> None:
    if not category or not category.strip():
        raise MigrationError("category name is empty")
    if category != category.strip():
        raise MigrationError(f"category name has surrounding whitespace: {category!r}")
    if len(category) > _MAX_CATEGORY_LEN:
        raise MigrationError(f"category name too long (>{_MAX_CATEGORY_LEN}): {category!r}")
    for bad in ("/", "\\", "__", ".."):
        if bad in category:
            raise MigrationError(f"category name may not contain {bad!r}: {category!r}")


def normalize_category(value: object) -> str | None:
    """Return a storable category, or None when the value is unusable.

    This is deliberately *not* the same policy as ``_validate_category_name``.
    That function is the strict, migration-time validator: it is building a
    ``safe_source_id`` directory name from scratch and owns the whole
    namespace, so it can afford (and needs) to refuse ``__``/``..``/etc. to
    avoid directory collisions it would itself create.

    ``normalize_category`` is the lenient, runtime normalizer: it is reading
    a category segment out of an *existing* directory name. A
    ``safe_source_id`` collision is a hazard for any path segment, not
    something specific to category, and it is already guarded elsewhere (the
    ownership marker written by ``ensure_library_dir``). Rejecting ``__`` or
    ``..`` here would be inconsistent with how every other path segment is
    treated and would silently discard a legitimate, pre-existing folder
    name. This function never raises — callers (discovery, batch import) must
    be able to degrade a bad value to None and keep going rather than abort
    ingest over a folder naming quirk.
    """
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped:
        return None
    if len(stripped) > _MAX_CATEGORY_LEN:
        return None
    if "/" in stripped or "\\" in stripped:
        return None
    return stripped


def transform_source_id(source_id: str, mapping: dict[str, str]) -> str:
    """Insert the category segment in front of an artist-rooted source id.

    The artist lookup runs before the segment-count check so an already
    migrated id (its first segment is a category, not an artist) fails with
    "unknown artist" rather than a misleading segment-count error.
    """
    segments = source_id.split("/")
    artist = segments[0] if segments else ""
    category = mapping.get(artist)
    if category is None:
        raise MigrationError(f"unknown artist for source_id {source_id!r}: {artist!r}")
    if len(segments) != _EXPECTED_SEGMENTS:
        raise MigrationError(f"expected {_EXPECTED_SEGMENTS} segments, got {len(segments)}: {source_id!r}")
    return f"{category}/{source_id}"


def transform_path(path: str, root: str, mapping: dict[str, str]) -> str:
    """Insert the category segment into an absolute path under ``root``."""
    root_prefix = root.rstrip("/") + "/"
    if not path.startswith(root_prefix):
        raise MigrationError(f"path is outside library root {root!r}: {path!r}")
    remainder = path[len(root_prefix) :]
    artist, sep, rest = remainder.partition("/")
    if not sep:
        raise MigrationError(f"path has no artist segment: {path!r}")
    category = mapping.get(artist)
    if category is None:
        raise MigrationError(f"unknown artist for path {path!r}: {artist!r}")
    return f"{root_prefix}{category}/{artist}/{rest}"


def assert_safe_source_id_unique(new_source_ids: list[str]) -> None:
    """safe_source_id is not injective; two ids must never share a library dir."""
    seen: dict[str, str] = {}
    for source_id in new_source_ids:
        safe = safe_source_id(source_id)
        previous = seen.get(safe)
        if previous is not None:
            raise MigrationError(f"library directory collision: {previous!r} and {source_id!r} both map to {safe!r}")
        seen[safe] = source_id
