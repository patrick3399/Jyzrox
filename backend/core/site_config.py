"""Unified site configuration service — M1.

Merge priority:  manual override (DB)  >  adaptive auto-tune (DB)  >  _sites.py defaults

Cache: in-memory dict, 30s TTL, immediate invalidation via Redis Pub/Sub.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from functools import lru_cache

from sqlalchemy import select

from core.database import AsyncSessionLocal
from core.redis_client import get_redis
from db.models import SiteConfig
from plugins.builtin.gallery_dl._sites import gdl_extractor_name, get_site_config

logger = logging.getLogger(__name__)

_INVALIDATION_CHANNEL = "site_config:invalidate"

# Fields allowed in overrides.download
_DOWNLOAD_FIELDS = {
    "retries",
    "http_timeout",
    "sleep_request",
    "sleep_download",
    "concurrency",
    "inactivity_timeout",
    "browser_profile",
    "proxy_url",
    "rate_limit",
    "spread_personas",
}

# Sections of SiteConfig.overrides that a reset may clear as a whole
_OVERRIDE_SECTIONS = frozenset({"download", "field_mapping"})

# Jyzrox canonical field names allowed in overrides.field_mapping
JYZROX_FIELDS = frozenset(
    {
        "source_id",
        "title",
        "artist",
        "tags",
        "date",
        "title_jpn",
        "category",
        "language",
        "uploader",
    }
)


@dataclass(frozen=True, slots=True)
class DownloadParams:
    """Effective download parameters for a source (after merge)."""

    retries: int = 4
    http_timeout: int = 30
    sleep_request: float | tuple[float, float] | None = None  # API/page requests (gallery-dl sleep-request)
    sleep_download: float | tuple[float, float] | None = None  # per file download (gallery-dl sleep)
    concurrency: int = 2
    inactivity_timeout: int = 300
    browser_profile: str | None = None
    proxy_url: str | None = None
    rate_limit: str | None = None
    spread_personas: bool = False  # ADR 0022: concurrency becomes the per-persona cap


class SiteConfigService:
    """Singleton service for per-site download configuration.

    Initialized in main.py (API) and worker/__init__.py (Worker).
    Both containers maintain independent caches, synced via Redis Pub/Sub.
    """

    def __init__(self) -> None:
        self._cache: dict[str, tuple[DownloadParams, float]] = {}
        self._batch_cache: tuple[dict[str, DownloadParams], float] | None = None
        self._ttl: float = 30.0
        self._listener_task: asyncio.Task | None = None

    # ── Public API ────────────────────────────────────────────────────

    async def get_effective_download_params(self, source_id: str) -> DownloadParams:
        """Return merged download params: override > adaptive > _sites.py."""
        cached = self._cache.get(source_id)
        if cached is not None:
            params, ts = cached
            if time.time() - ts < self._ttl:
                return params

        params = await self._load_and_merge(source_id)
        self._cache[source_id] = (params, time.time())
        return params

    async def update(self, source_id: str, overrides: dict) -> tuple[DownloadParams, SiteConfig]:
        """Update user overrides for a source. Returns (params, row)."""
        self._validate_overrides(overrides)

        async with AsyncSessionLocal() as session:
            row = await session.get(SiteConfig, source_id)
            if row is None:
                merged = overrides
            else:
                # Deep merge: update nested dicts
                merged = dict(row.overrides)
                for key, val in overrides.items():
                    if isinstance(val, dict) and isinstance(merged.get(key), dict):
                        merged[key] = {**merged[key], **val}
                    else:
                        merged[key] = val
            if _TIMING_FIELDS & overrides.get("download", {}).keys():
                self._validate_sleep_fits_inactivity(
                    self._compose(source_id, merged, row.adaptive if row is not None else None)
                )
            if row is None:
                row = SiteConfig(source_id=source_id, overrides=merged)
                session.add(row)
            else:
                row.overrides = merged
            await session.commit()
            result = self._merge(source_id, row)
            session.expunge(row)

        await self._invalidate(source_id)
        return result, row

    async def reset(self, source_id: str, field_path: str) -> tuple[DownloadParams, SiteConfig | None]:
        """Remove override(s). 'download' / 'field_mapping' drops a whole section;
        'download.retries' drops one field. Returns (params, row)."""
        parts = field_path.split(".")
        if len(parts) not in (1, 2) or not all(parts) or (len(parts) == 1 and parts[0] not in _OVERRIDE_SECTIONS):
            raise ValueError(f"field_path must be 'download', 'field_mapping' or 'section.field', got '{field_path}'")

        section = parts[0]
        field = parts[1] if len(parts) == 2 else None

        async with AsyncSessionLocal() as session:
            row = await session.get(SiteConfig, source_id)
            if row is not None and section in row.overrides:
                updated = dict(row.overrides)
                if field is None:
                    updated.pop(section, None)
                else:
                    section_dict = dict(updated.get(section, {}))
                    section_dict.pop(field, None)
                    if section_dict:
                        updated[section] = section_dict
                    else:
                        updated.pop(section, None)
                row.overrides = updated
                await session.commit()
            if row is not None:
                session.expunge(row)
            result = self._merge(source_id, row)

        await self._invalidate(source_id)
        return result, row

    async def reset_adaptive(self, source_id: str) -> tuple[DownloadParams, SiteConfig | None]:
        """Clear all adaptive state for a source. Returns (params, row)."""
        from core.adaptive import adaptive_engine

        async with AsyncSessionLocal() as session:
            row = await session.get(SiteConfig, source_id)
            # Reset the Redis adaptive runtime state BEFORE committing the DB
            # clear (edge case #138). If the process dies between the two, the
            # only surviving inconsistency is a cleared Redis with an un-cleared
            # DB row, which the next adaptive write self-heals; the reverse
            # (stale Redis state surviving a cleared DB row across restart) is
            # not self-healing.
            await adaptive_engine.reset(source_id)
            if row is not None:
                row.adaptive = {}
                await session.commit()
                session.expunge(row)
            result = self._merge(source_id, row)

        await self._invalidate(source_id)
        return result, row

    async def save_probe_result(self, source_id: str, probe_data: dict) -> None:
        """Persist probe result to the auto_probe JSONB column."""
        async with AsyncSessionLocal() as session:
            row = await session.get(SiteConfig, source_id)
            if row is None:
                row = SiteConfig(source_id=source_id, auto_probe=probe_data)
                session.add(row)
            else:
                row.auto_probe = probe_data
            await session.commit()

    async def save_field_mapping(self, source_id: str, field_mapping: dict) -> tuple[DownloadParams, SiteConfig]:
        """Save user-confirmed field mappings to overrides.field_mapping. Returns (params, row)."""
        _validate_field_mapping(field_mapping)
        return await self.update(source_id, {"field_mapping": field_mapping})

    async def get_params_with_row(self, source_id: str) -> tuple[DownloadParams, SiteConfig | None]:
        """Return merged download params AND the DB row in a single query."""
        async with AsyncSessionLocal() as session:
            row = (
                await session.execute(select(SiteConfig).where(SiteConfig.source_id == source_id))
            ).scalar_one_or_none()
            if row is not None:
                session.expunge(row)
        params = self._merge(source_id, row)
        self._cache[source_id] = (params, time.time())
        return params, row

    async def get_all_with_rows(self) -> list[tuple[str, DownloadParams, SiteConfig | None]]:
        """Return all sources with params and DB rows in a single query.

        Also populates the batch params cache (same as get_all_download_params).
        """
        from plugins.builtin.gallery_dl._sites import all_sites

        db_rows: dict[str, SiteConfig] = {}
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(SiteConfig))
            for row in result.scalars().all():
                session.expunge(row)
                db_rows[row.source_id] = row

        seen: set[str] = set()
        output: list[tuple[str, DownloadParams, SiteConfig | None]] = []
        params_cache: dict[str, DownloadParams] = {}
        for site in all_sites():
            if site.source_id in seen:
                continue
            seen.add(site.source_id)
            row = db_rows.get(site.source_id)
            params = self._merge(site.source_id, row)
            output.append((site.source_id, params, row))
            params_cache[site.source_id] = params

        self._batch_cache = (params_cache, time.time())
        return output

    async def get_all_download_params(self) -> dict[str, DownloadParams]:
        """Return effective download params for ALL known sources.

        Uses a single DB query to fetch all rows, then merges with _sites.py defaults.
        Results are cached with the same TTL as individual lookups.
        """
        if self._batch_cache is not None:
            output, ts = self._batch_cache
            if time.time() - ts < self._ttl:
                return output

        from plugins.builtin.gallery_dl._sites import all_sites

        # Batch-load all DB rows in one query
        db_rows: dict[str, SiteConfig] = {}
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(SiteConfig))
            for row in result.scalars().all():
                db_rows[row.source_id] = row

        # Merge for each unique source
        seen: set[str] = set()
        output: dict[str, DownloadParams] = {}
        for site in all_sites():
            if site.source_id in seen:
                continue
            seen.add(site.source_id)
            output[site.source_id] = self._merge(site.source_id, db_rows.get(site.source_id))

        self._batch_cache = (output, time.time())
        return output

    def defaults(self, source_id: str) -> DownloadParams:
        """Jyzrox-layer defaults (no overrides, no adaptive): what a reset falls back to."""
        return self._merge(source_id, None)

    def extractor_defaults(self, source_id: str) -> dict:
        """gallery-dl's built-in pacing for the source's extractor (informational hint).

        Read from the in-process gallery-dl, which may differ from the venv one
        that runs the jobs. A null sleep here means gallery-dl does not sleep.
        """
        try:
            return dict(_extractor_defaults_for(gdl_extractor_name(source_id)))
        except Exception:
            logger.warning("[site_config] extractor default lookup failed for %s", source_id, exc_info=True)
            return {"sleep_request": None, "sleep_download": None}

    # ── Pub/Sub Listener ──────────────────────────────────────────────

    async def start_listener(self) -> None:
        """Start Redis Pub/Sub listener for cross-container cache invalidation."""
        from core.redis_client import pubsub_listen_forever

        self._listener_task = asyncio.create_task(
            pubsub_listen_forever(
                _INVALIDATION_CHANNEL,
                self._evict,
                on_subscribe=self._drop_cache,
                name="site_config",
            ),
            name="site_config_listener",
        )

    async def stop_listener(self) -> None:
        """Cancel the Pub/Sub listener task on shutdown."""
        if self._listener_task is not None and not self._listener_task.done():
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
        self._listener_task = None

    async def _evict(self, data) -> None:
        """Evict the cache entry named by an invalidation message."""
        source_id = data.decode() if isinstance(data, bytes) else data
        if not isinstance(source_id, str):
            raise TypeError(f"invalidation payload is {type(source_id).__name__}, not str")
        self._cache.pop(source_id, None)
        self._batch_cache = None

    async def _drop_cache(self) -> None:
        """Discard the whole cache after every (re)subscribe.

        Invalidations published while the connection was down are gone, so any
        entry held across the gap may be stale.
        """
        self._cache.clear()
        self._batch_cache = None

    # ── Internal ──────────────────────────────────────────────────────

    async def _invalidate(self, source_id: str) -> None:
        """Evict cache entry and publish cross-container invalidation."""
        self._cache.pop(source_id, None)
        self._batch_cache = None
        try:
            await get_redis().publish(_INVALIDATION_CHANNEL, source_id)
        except Exception:
            logger.warning("[site_config] failed to publish invalidation for %s", source_id)

    async def _load_and_merge(self, source_id: str) -> DownloadParams:
        """Load single row from DB and merge with _sites.py defaults."""
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(SiteConfig).where(SiteConfig.source_id == source_id))
            row = result.scalar_one_or_none()

        return self._merge(source_id, row)

    def _merge(self, source_id: str, row: SiteConfig | None) -> DownloadParams:
        """Merge DB row with _sites.py defaults. Pure function (no I/O)."""
        if row is None:
            return self._compose(source_id, None, None)
        return self._compose(source_id, row.overrides, row.adaptive)

    @staticmethod
    def _compose(source_id: str, overrides: dict | None, adaptive: dict | None) -> DownloadParams:
        """Layer overrides > adaptive > _sites.py defaults. Pure function (no I/O)."""
        site_defaults = get_site_config(source_id)

        # Start with _sites.py defaults
        base: dict = {
            "retries": site_defaults.retries,
            "http_timeout": site_defaults.http_timeout,
            "sleep_request": site_defaults.sleep_request,
            "sleep_download": site_defaults.sleep_download,
            "concurrency": 2,  # not in GdlSiteConfig; default 2
            "inactivity_timeout": site_defaults.inactivity_timeout,
        }

        # Layer 2: adaptive (lower priority than override)
        adaptive_dl = adaptive.get("download", {}) if adaptive else {}
        for field in _DOWNLOAD_FIELDS:
            if field in adaptive_dl:
                base[field] = adaptive_dl[field]

        # Layer 3: manual overrides (highest priority)
        override_dl = overrides.get("download", {}) if overrides else {}
        for field in _DOWNLOAD_FIELDS:
            if field in override_dl:
                base[field] = override_dl[field]

        # JSON round-trips a [min, max] pair as a list; keep the dataclass shape stable.
        for field in _SLEEP_FIELDS:
            if isinstance(base[field], list):
                base[field] = tuple(base[field])

        return DownloadParams(**base)

    @staticmethod
    def _validate_sleep_fits_inactivity(params: DownloadParams) -> None:
        """A single sleep that outlasts the watchdog window would be killed as idle."""
        for name in _SLEEP_FIELDS:
            value = getattr(params, name)
            if value is None:
                continue
            longest = max(value) if isinstance(value, tuple) else value
            if longest >= params.inactivity_timeout:
                raise ValueError(
                    f"{name} ({longest}s) must be shorter than inactivity_timeout ({params.inactivity_timeout}s)"
                )

    @staticmethod
    def _validate_overrides(overrides: dict) -> None:
        """Validate override values before persisting."""
        dl = overrides.get("download", {})
        if "concurrency" in dl:
            c = dl["concurrency"]
            if not isinstance(c, int) or c < 1 or c > 20:
                raise ValueError(f"concurrency must be 1-20, got {c}")
        if "spread_personas" in dl and not isinstance(dl["spread_personas"], bool):
            raise ValueError("spread_personas must be a boolean")
        if "retries" in dl:
            r = dl["retries"]
            if not isinstance(r, int) or r < 0 or r > 50:
                raise ValueError(f"retries must be 0-50, got {r}")
        if "http_timeout" in dl:
            t = dl["http_timeout"]
            if not isinstance(t, int) or t < 5 or t > 300:
                raise ValueError(f"http_timeout must be 5-300, got {t}")
        if "inactivity_timeout" in dl:
            t = dl["inactivity_timeout"]
            if not isinstance(t, int) or t < 30 or t > 3600:
                raise ValueError(f"inactivity_timeout must be 30-3600, got {t}")
        for name in _SLEEP_FIELDS:
            if name in dl:
                _validate_sleep(name, dl[name])
        if "browser_profile" in dl:
            bp = dl["browser_profile"]
            if bp is not None and bp not in ("chrome", "firefox"):
                raise ValueError("browser_profile must be 'chrome', 'firefox', or null")
        if "proxy_url" in dl:
            pu = dl["proxy_url"]
            # No SOCKS: gallery-dl is the only consumer and its isolated venv has
            # no PySocks, so a socks5:// proxy would fail every download.
            if pu is not None and not pu.startswith(("http://", "https://")):
                raise ValueError("proxy_url must start with http:// or https:// (SOCKS proxies are not supported)")

        fm = overrides.get("field_mapping", {})
        if fm:
            _validate_field_mapping(fm)


# ── Module-level helpers ──────────────────────────────────────────────

_SLEEP_FIELDS = ("sleep_request", "sleep_download")
# Fields whose cross-check (sleep < inactivity_timeout) must rerun when they change.
_TIMING_FIELDS = frozenset({*_SLEEP_FIELDS, "inactivity_timeout"})
_MAX_SLEEP_S = 3600


def _is_seconds(x) -> bool:
    return isinstance(x, int | float) and not isinstance(x, bool) and 0 <= x <= _MAX_SLEEP_S


def _validate_sleep(name: str, value) -> None:
    """Validate a sleep setting: null, seconds, or a [min, max] pair (0 = explicitly off)."""
    if value is None:
        return
    if isinstance(value, list | tuple):
        if len(value) != 2 or not all(_is_seconds(x) for x in value) or value[0] > value[1]:
            raise ValueError(f"{name} pair must be [min, max] with 0 <= min <= max <= {_MAX_SLEEP_S}, got {value}")
    elif not _is_seconds(value):
        raise ValueError(f"{name} must be null, a number or [min, max] within 0..{_MAX_SLEEP_S}, got {value!r}")


def _interval_hint(value) -> float | list[float] | None:
    """Normalise a gallery-dl request_interval/download_interval; 0 (no sleep) is None."""
    if isinstance(value, tuple | list) and len(value) == 2 and all(isinstance(x, int | float) for x in value):
        return [float(value[0]), float(value[1])] if any(value) else None
    if isinstance(value, int | float) and not isinstance(value, bool) and value > 0:
        return float(value)
    return None


@lru_cache(maxsize=256)
def _extractor_defaults_for(category: str) -> dict:
    """First in-process gallery-dl extractor class of `category` decides its built-in pacing."""
    nulls = {"sleep_request": None, "sleep_download": None}
    try:
        from gallery_dl import extractor as gdl_extractor

        for cls in gdl_extractor.extractors():
            if getattr(cls, "category", None) == category:
                return {
                    "sleep_request": _interval_hint(getattr(cls, "request_interval", 0)),
                    "sleep_download": _interval_hint(getattr(cls, "download_interval", 0)),
                }
    except Exception:
        logger.warning("[site_config] gallery-dl extractor scan failed for %s", category, exc_info=True)
    return nulls


def _validate_field_mapping(field_mapping: dict) -> None:
    """Validate a field_mapping dict: keys must be Jyzrox fields, values str or None."""
    for key in field_mapping:
        if key not in JYZROX_FIELDS:
            raise ValueError(f"Unknown Jyzrox field in field_mapping: '{key}'")
    for val in field_mapping.values():
        if val is not None and not isinstance(val, str):
            raise ValueError(f"field_mapping values must be strings or null, got {type(val).__name__}")


# ── Module-level singleton ────────────────────────────────────────────

site_config_service = SiteConfigService()
