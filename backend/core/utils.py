"""Shared utility functions used across routers and workers."""


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
MOUNT_EXCLUDE_FS: frozenset[str] = frozenset({
    'proc', 'sysfs', 'devpts', 'tmpfs', 'cgroup', 'cgroup2', 'overlay',
    'mqueue', 'devtmpfs', 'hugetlbfs', 'securityfs', 'pstore',
    'debugfs', 'tracefs', 'fusectl', 'configfs', 'nsfs',
    'autofs', 'binfmt_misc', 'efivarfs',
})
MOUNT_EXCLUDE_PATHS: frozenset[str] = frozenset({
    '/', '/proc', '/sys', '/dev', '/run', '/tmp',
    '/etc/resolv.conf', '/etc/hostname', '/etc/hosts',
})
