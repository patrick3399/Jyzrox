"""Shared utility functions used across routers and workers."""

import functools
from urllib.parse import urlsplit, urlunsplit

from fastapi import HTTPException


def validate_cron(expr: str) -> None:
    """Validate a cron expression. Raises HTTPException(400) if invalid."""
    from croniter import croniter

    try:
        croniter(expr)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid cron expression: {exc}")


def escape_like(s: str) -> str:
    """Escape backslash, %, and _ for use in SQLAlchemy .ilike(..., escape='\\')."""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@functools.cache
def _opencc(config: str):
    # Lazy: building a converter loads its dictionaries, and this module is
    # imported by workers that never search.
    from opencc import OpenCC

    return OpenCC(config)


def zh_variants(q: str) -> list[str]:
    """Return q plus its simplified and traditional forms, deduplicated.

    Use for ILIKE matching so "魚子醬" and "鱼子酱" find each other. Plain
    t2s/s2t only: s2twp rewrites phrases (软件 -> 軟體), which would stop a
    traditional title written 軟件 from matching. s2t is one-to-many for a few
    characters (发 -> 發, never 髮), so a simplified query can miss those.
    Text without Chinese characters comes back as [q].
    """
    return list(dict.fromkeys([q, _opencc("t2s").convert(q), _opencc("s2t").convert(q)]))


def normalize_subscription_url(url: str) -> str:
    """Strip whitespace and trailing slashes for consistent duplicate detection."""
    return url.strip().rstrip("/")


def normalize_download_url(url: str) -> str:
    """Return the stable identity used to deduplicate download requests.

    Fragments are browser-local and never affect downloaded content. Trailing
    slashes are also ignored, while query strings remain byte-for-byte intact
    because signed download URLs can depend on their original ordering.
    """
    stripped = url.strip()
    parts = urlsplit(stripped)
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))


def detect_source(url: str) -> str:
    """Auto-detect download source from URL domain."""
    from plugins.registry import plugin_registry

    result = plugin_registry.detect_source(url)
    return result or "unknown"


def detect_source_info(url: str) -> dict | None:
    """Return site info dict for the given URL, or None."""
    from plugins.registry import plugin_registry

    info = plugin_registry.detect_source_info(url)
    return info.model_dump() if info else None


def get_supported_sites() -> dict[str, list[dict]]:
    """Return sites grouped by category."""
    from plugins.registry import plugin_registry

    return plugin_registry.get_supported_sites_grouped()


# Shared mount-point filtering constants for psutil.disk_partitions()
MOUNT_EXCLUDE_FS: frozenset[str] = frozenset(
    {
        "proc",
        "sysfs",
        "devpts",
        "tmpfs",
        "cgroup",
        "cgroup2",
        "overlay",
        "mqueue",
        "devtmpfs",
        "hugetlbfs",
        "securityfs",
        "pstore",
        "debugfs",
        "tracefs",
        "fusectl",
        "configfs",
        "nsfs",
        "autofs",
        "binfmt_misc",
        "efivarfs",
    }
)
MOUNT_EXCLUDE_PATHS: frozenset[str] = frozenset(
    {
        "/",
        "/proc",
        "/sys",
        "/dev",
        "/run",
        "/tmp",
        "/etc/resolv.conf",
        "/etc/hostname",
        "/etc/hosts",
    }
)
