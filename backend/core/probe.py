"""M2 Probe Engine — analyze a URL via gallery-dl --dump-json.

Provides SSRF protection (scheme allowlist + DNS private-range rejection),
runs gallery-dl as a subprocess, and produces field-level metadata analysis
with suggested Jyzrox field mappings.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import re
import socket
from dataclasses import dataclass, field
from urllib.parse import urlparse

from core.site_config import JYZROX_FIELDS

logger = logging.getLogger(__name__)

# Maximum bytes of subprocess stdout before the process is killed.
_MAX_OUTPUT_BYTES = 2 * 1024 * 1024  # 2 MB

# Probe subprocess timeout in seconds.
_PROBE_TIMEOUT = 60

# Maximum length for a single string field value in probe output.
_MAX_FIELD_VALUE_LEN = 10_240

# Gallery-dl internal fields to exclude from analysis.
_SKIP_FIELD_PREFIXES = ("_",)
_SKIP_FIELDS = frozenset({"category", "subcategory"})

# Scoring table: jyzrox_field → list of (key_hint, score_boost)
# Exact key matches earn 0.9; partial matches 0.7; type-only matches 0.3.
_ROLE_HINTS: dict[str, list[tuple[str, float]]] = {
    "source_id": [("gallery_id", 0.9), ("id", 0.7)],
    "title": [("title", 0.9), ("title_en", 0.7), ("description", 0.5), ("content", 0.4)],
    "artist": [("uploader", 0.9), ("username", 0.7), ("author", 0.7)],
    "tags": [("tags", 0.9)],
    "date": [("date", 0.9), ("posted", 0.7)],
    "title_jpn": [("title_jpn", 0.9), ("title_original", 0.7)],
    "category": [("gallery_category", 0.9), ("category", 0.7)],
    "language": [("lang", 0.9), ("language", 0.7)],
    "uploader": [("uploader", 0.9), ("username", 0.7)],
}

# Guard: all _ROLE_HINTS keys must be valid Jyzrox canonical field names.
assert frozenset(_ROLE_HINTS) <= JYZROX_FIELDS, (
    f"_ROLE_HINTS contains unknown Jyzrox fields: {frozenset(_ROLE_HINTS) - JYZROX_FIELDS}"
)

# Preferred field types per Jyzrox role.
_ROLE_PREFERRED_TYPES: dict[str, frozenset[str]] = {
    "source_id": frozenset({"numeric_id", "text"}),
    "title": frozenset({"text"}),
    "artist": frozenset({"text"}),
    "tags": frozenset({"namespaced_tags", "flat_tags"}),
    "date": frozenset({"datetime", "timestamp"}),
    "title_jpn": frozenset({"text"}),
    "category": frozenset({"text"}),
    "language": frozenset({"text"}),
    "uploader": frozenset({"text"}),
}

# ISO 8601 / common date patterns.
_DATE_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}"  # YYYY-MM-DD
    r"([ T]\d{2}:\d{2}(:\d{2})?([+-]\d{2}:?\d{2}|Z)?)?"  # optional time
    r"$"
)

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
class ProbeField:
    key: str
    field_type: str  # url/datetime/timestamp/namespaced_tags/flat_tags/numeric_id/text
    sample_value: str
    level: str  # "gallery" or "page"


@dataclass
class FieldMapping:
    jyzrox_field: str
    gdl_field: str | None  # None = unmapped
    confidence: float
    suggested: bool


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
    loop = asyncio.get_event_loop()
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

    Uses --config /dev/null to prevent cookie leakage.
    Enforces 2 MB output cap and 60s total timeout.
    Returns empty list on any error.
    """
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
        url,
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
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


def _validate_probe_output(raw: list[dict]) -> list[dict]:
    """Truncate any string fields longer than 10 KB to prevent UI bloat."""
    cleaned: list[dict] = []
    for item in raw:
        new_item: dict = {}
        for key, val in item.items():
            if isinstance(val, str) and len(val) > _MAX_FIELD_VALUE_LEN:
                new_item[key] = val[:_MAX_FIELD_VALUE_LEN] + "..."
            else:
                new_item[key] = val
        cleaned.append(new_item)
    return cleaned


def _diff_fields(items: list[dict]) -> list[ProbeField]:
    """Classify each field as gallery-level (constant) or page-level (varies).

    Skips internal fields (starting with '_') and category/subcategory.
    """
    if not items:
        return []

    # Collect all field keys across items.
    all_keys: set[str] = set()
    for item in items:
        all_keys.update(item.keys())

    result: list[ProbeField] = []
    for key in sorted(all_keys):
        if key in _SKIP_FIELDS:
            continue
        if any(key.startswith(p) for p in _SKIP_FIELD_PREFIXES):
            continue

        # Gather values for this key across all items.
        values = [item[key] for item in items if key in item]
        if not values:
            continue

        # Determine gallery vs page level.
        # Use string representation for comparison to handle unhashable types.
        str_values = [json.dumps(v, sort_keys=True, default=str) for v in values]
        level = "gallery" if len(set(str_values)) == 1 else "page"

        field_type = _fingerprint_field(key, values)

        # Build a concise sample value for UI display.
        sample_raw = values[0]
        if isinstance(sample_raw, dict | list):
            sample = json.dumps(sample_raw, ensure_ascii=False)[:200]
        else:
            sample = str(sample_raw)[:200]

        result.append(ProbeField(key=key, field_type=field_type, sample_value=sample, level=level))

    return result


def _fingerprint_field(_key: str, values: list) -> str:
    """Infer the semantic type of a field from its values."""
    # Use the first non-None value for type detection.
    sample = next((v for v in values if v is not None), None)
    if sample is None:
        return "text"

    if isinstance(sample, dict):
        # namespaced_tags: dict with string keys mapping to lists of strings.
        if all(isinstance(v, list) for v in sample.values()):
            return "namespaced_tags"
        return "text"

    if isinstance(sample, list):
        if all(isinstance(el, str) for el in sample):
            return "flat_tags"
        return "text"

    if isinstance(sample, bool):
        return "text"

    if isinstance(sample, int):
        if sample > 1_000_000_000:
            return "timestamp"
        return "numeric_id"

    if isinstance(sample, float):
        if sample > 1_000_000_000.0:
            return "timestamp"
        return "text"

    if isinstance(sample, str):
        if sample.startswith("http://") or sample.startswith("https://"):
            return "url"
        if _DATE_RE.match(sample.strip()):
            return "datetime"
        if sample.isdigit():
            return "numeric_id"
        return "text"

    return "text"


def _score_mappings(fields: list[ProbeField], _items: list[dict]) -> list[FieldMapping]:
    """For each Jyzrox canonical field, find the best-matching gallery-dl field.

    Scoring rules:
    - Exact key match: 0.9
    - Partial key match (hint is substring of key or vice versa): 0.7
    - Type-only match (no key hint): 0.3
    Only includes mappings with confidence >= 0.3.
    """
    field_by_key = {f.key: f for f in fields}
    # Per design spec: only gallery-level fields are mapping candidates.
    gallery_fields = {k: f for k, f in field_by_key.items() if f.level == "gallery"}
    mappings: list[FieldMapping] = []

    for jyzrox_role, hints in _ROLE_HINTS.items():
        preferred_types = _ROLE_PREFERRED_TYPES.get(jyzrox_role, frozenset())

        best_key: str | None = None
        best_score: float = 0.0

        for gdl_field, probe_field in gallery_fields.items():
            # source_id "id" hint only counts if type is numeric_id.
            score = 0.0
            for hint, hint_score in hints:
                if gdl_field == hint:
                    if hint == "id" and jyzrox_role == "source_id" and probe_field.field_type != "numeric_id":
                        continue
                    score = max(score, hint_score)
                elif hint in gdl_field or gdl_field in hint:
                    score = max(score, 0.7)

            # Type-only boost when no key hint matched.
            if score == 0.0 and probe_field.field_type in preferred_types:
                score = 0.3
            elif score > 0.0 and probe_field.field_type in preferred_types:
                # Small bonus for correct type.
                score = min(1.0, score + 0.05)

            if score > best_score:
                best_score = score
                best_key = gdl_field

        if best_score >= 0.3 and best_key is not None:
            mappings.append(
                FieldMapping(
                    jyzrox_field=jyzrox_role,
                    gdl_field=best_key,
                    confidence=round(best_score, 3),
                    suggested=True,
                )
            )
        else:
            # Include unmapped entries so callers know the field is unresolved.
            mappings.append(
                FieldMapping(
                    jyzrox_field=jyzrox_role,
                    gdl_field=None,
                    confidence=0.0,
                    suggested=False,
                )
            )

    return mappings


def _detect_source(raw: list[dict]) -> str | None:
    """Detect the gallery-dl source_id by matching 'category' in GDL_SITES."""
    if not raw:
        return None

    gdl_category = raw[0].get("category")
    if not gdl_category:
        return None

    from plugins.builtin.gallery_dl._sites import GDL_SITES

    gdl_category_lower = str(gdl_category).lower()
    for site in GDL_SITES:
        # gallery-dl 'category' field typically matches the extractor name.
        extractor_name = site.extractor or site.source_id
        if extractor_name.lower() == gdl_category_lower or site.source_id.lower() == gdl_category_lower:
            return site.source_id

    return None
