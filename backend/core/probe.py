"""M2 Probe Engine — analyze a URL via gallery-dl --dump-json.

Provides SSRF protection (scheme allowlist + DNS private-range rejection),
runs gallery-dl as a subprocess, and produces field-level metadata analysis
with suggested Jyzrox field mappings.
"""

import asyncio
import ipaddress
import json
import logging
import socket
from dataclasses import dataclass, field
from urllib.parse import urlparse

from core.probe_analysis import (
    FieldMapping as FieldMapping,
)
from core.probe_analysis import (
    ProbeField as ProbeField,
)
from core.probe_analysis import (
    _detect_source,
    _diff_fields,
    _score_mappings,
    _validate_probe_output,
)
from core.probe_analysis import (
    _fingerprint_field as _fingerprint_field,
)

logger = logging.getLogger(__name__)

# Maximum bytes of subprocess stdout before the process is killed.
_MAX_OUTPUT_BYTES = 2 * 1024 * 1024  # 2 MB

# Probe subprocess timeout in seconds.
_PROBE_TIMEOUT = 60

# Private / reserved IP ranges for SSRF protection.
_PRIVATE_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local
    ipaddress.ip_network("100.64.0.0/10"),  # shared address space
    ipaddress.ip_network("192.0.0.0/24"),  # IETF protocol
    ipaddress.ip_network("198.18.0.0/15"),  # benchmarking
    ipaddress.ip_network("198.51.100.0/24"),  # documentation
    ipaddress.ip_network("203.0.113.0/24"),  # documentation
    ipaddress.ip_network("224.0.0.0/4"),  # multicast
    ipaddress.ip_network("240.0.0.0/4"),  # reserved
    ipaddress.ip_network("::1/128"),  # loopback
    ipaddress.ip_network("fe80::/10"),  # link-local
    ipaddress.ip_network("fc00::/7"),  # unique local
    ipaddress.ip_network("ff00::/8"),  # multicast
]

# ── Dataclasses ───────────────────────────────────────────────────────────────


@dataclass
class ProbeResult:
    success: bool
    error: str | None = None
    raw_metadata: list[dict] = field(default_factory=list)
    fields: list[ProbeField] = field(default_factory=list)
    suggested_mappings: list[FieldMapping] = field(default_factory=list)
    detected_source: str | None = None


# ── Public entry point ────────────────────────────────────────────────────────


async def probe_url(url: str) -> ProbeResult:
    """Full orchestration: validate → SSRF check → run gallery-dl → analyze.

    Returns a ProbeResult. Never raises — errors are surfaced via result.error.
    """
    try:
        _validate_url(url)
    except ValueError as exc:
        return ProbeResult(success=False, error=str(exc))

    parsed = urlparse(url)
    hostname = parsed.hostname
    if not hostname:
        return ProbeResult(success=False, error="Cannot parse hostname from URL")

    try:
        await _check_dns(hostname)
    except ValueError as exc:
        return ProbeResult(success=False, error=str(exc))
    except Exception as exc:
        return ProbeResult(success=False, error=f"DNS resolution failed: {exc}")

    raw = await _run_gallery_dl_probe(url)
    if not raw:
        return ProbeResult(success=False, error="gallery-dl returned no metadata")

    raw = _validate_probe_output(raw)
    fields = _diff_fields(raw)
    mappings = _score_mappings(fields, raw)
    detected = _detect_source(raw)

    return ProbeResult(
        success=True,
        raw_metadata=raw,
        fields=fields,
        suggested_mappings=mappings,
        detected_source=detected,
    )


# ── Internal helpers ──────────────────────────────────────────────────────────


def _validate_url(url: str) -> None:
    """Allow only http/https schemes. Raise ValueError otherwise."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Unsupported URL scheme '{parsed.scheme}'. Only http and https are allowed.")
    if not parsed.netloc:
        raise ValueError("URL has no network location (host)")


async def _check_dns(hostname: str) -> None:
    """Resolve hostname and reject private/loopback/reserved IPs (SSRF prevention).

    Checks ALL returned addresses, not just the first.
    """
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise ValueError(f"Could not resolve hostname '{hostname}': {exc}") from exc

    if not infos:
        raise ValueError(f"No DNS results for hostname '{hostname}'")

    for info in infos:
        # info is (family, type, proto, canonname, sockaddr)
        sockaddr = info[4]
        ip_str = sockaddr[0]
        try:
            addr = ipaddress.ip_address(ip_str)
        except ValueError:
            continue

        for network in _PRIVATE_NETWORKS:
            if addr in network:
                raise ValueError(f"Blocked: '{hostname}' resolves to private/reserved IP {addr} (matches {network})")


async def _run_gallery_dl_probe(url: str) -> list[dict]:
    """Run gallery-dl --dump-json and parse each output line as JSON.

    Uses --config /dev/null to prevent cookie leakage while loading bundled
    custom extractors explicitly via --extractors.
    Enforces 2 MB output cap and 60s total timeout.
    Returns empty list on any error.
    """
    from plugins.builtin.gallery_dl._extractors import extractor_source_dirs
    from plugins.builtin.gallery_dl._subprocess_env import gdl_subprocess_env
    from worker.gallery_dl_venv import get_gdl_bin

    gdl_bin = get_gdl_bin()
    cmd = [
        gdl_bin,
        "--dump-json",
        "--range",
        "1-3",
        "--http-timeout",
        "15",
        "--config",
        "/dev/null",
    ]
    for source_dir in extractor_source_dirs():
        cmd.extend(("--extractors", source_dir))
    cmd.append(url)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=gdl_subprocess_env(),
        )

        chunks: list[bytes] = []
        total_bytes = 0
        killed = False

        assert proc.stdout is not None

        async def _read_with_cap() -> bytes:
            nonlocal total_bytes, killed
            while True:
                chunk = await proc.stdout.read(65536)  # type: ignore[union-attr]
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > _MAX_OUTPUT_BYTES:
                    logger.warning("[probe] Output exceeded 2 MB cap — killing gallery-dl")
                    proc.kill()
                    killed = True
                    break
                chunks.append(chunk)
            return b"".join(chunks)

        try:
            stdout_bytes = await asyncio.wait_for(_read_with_cap(), timeout=_PROBE_TIMEOUT)
        except TimeoutError:
            logger.warning("[probe] gallery-dl probe timed out after %ds", _PROBE_TIMEOUT)
            proc.kill()
            return []

        await proc.wait()

        if killed:
            return []

        lines = stdout_bytes.decode(errors="replace").splitlines()
        items: list[dict] = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    items.append(obj)
                elif isinstance(obj, list):
                    items.extend(x for x in obj if isinstance(x, dict))
            except json.JSONDecodeError:
                continue

        return items

    except Exception as exc:
        logger.warning("[probe] gallery-dl subprocess error: %s", exc)
        return []
