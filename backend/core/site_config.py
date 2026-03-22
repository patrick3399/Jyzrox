"""Unified site configuration service — M1.

Merge priority:  manual override (DB)  >  adaptive auto-tune (DB)  >  _sites.py defaults

Cache: in-memory dict, 30s TTL, immediate invalidation via Redis Pub/Sub.
"""

import asyncio
import logging
import time
from dataclasses import dataclass

from sqlalchemy import select

from core.database import AsyncSessionLocal
from core.redis_client import get_redis
from db.models import SiteConfig
from plugins.builtin.gallery_dl._sites import get_site_config

logger = logging.getLogger(__name__)

_INVALIDATION_CHANNEL = "site_config:invalidate"

# Fields allowed in overrides.download
_DOWNLOAD_FIELDS = {
    "retries",
    "http_timeout",
    "sleep_request",
    "concurrency",
    "inactivity_timeout",
    "browser_profile",
    "proxy_url",
    "rate_limit",
}

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
    sleep_request: float | tuple[float, float] | None = None
    concurrency: int = 2
    inactivity_timeout: int = 300
    browser_profile: str | None = None
    proxy_url: str | None = None
    rate_limit: str | None = None

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
                row = SiteConfig(source_id=source_id, overrides=overrides)
                session.add(row)
            else:
                # Deep merge: update nested dicts
                merged = dict(row.overrides)
                for key, val in overrides.items():
                    if isinstance(val, dict) and isinstance(merged.get(key), dict):
                        merged[key] = {**merged[key], **val}
                    else:
                        merged[key] = val
                row.overrides = merged
            await session.commit()
            result = self._merge(source_id, row)
            session.expunge(row)

        await self._invalidate(source_id)
        return result, row

    async def reset(self, source_id: str, field_path: str) -> tuple[DownloadParams, SiteConfig | None]:
        """Remove a specific override field. E.g. field_path='download.retries'. Returns (params, row)."""
        parts = field_path.split(".")
        if len(parts) != 2:
            raise ValueError(f"field_path must be 'section.field', got '{field_path}'")

        section, field = parts

        async with AsyncSessionLocal() as session:
            row = await session.get(SiteConfig, source_id)
            if row is not None and section in row.overrides:
                updated = dict(row.overrides)
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
        async with AsyncSessionLocal() as session:
            row = await session.get(SiteConfig, source_id)
            if row is not None:
                row.adaptive = {}
                await session.commit()
                session.expunge(row)
            result = self._merge(source_id, row)

        await self._invalidate(source_id)
        from core.adaptive import adaptive_engine

        await adaptive_engine.reset(source_id)
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
        from plugins.builtin.gallery_dl._sites import GDL_SITES

        db_rows: dict[str, SiteConfig] = {}
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(SiteConfig))
            for row in result.scalars().all():
                session.expunge(row)
                db_rows[row.source_id] = row

        seen: set[str] = set()
        output: list[tuple[str, DownloadParams, SiteConfig | None]] = []
        params_cache: dict[str, DownloadParams] = {}
        for site in GDL_SITES:
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

        from plugins.builtin.gallery_dl._sites import GDL_SITES

        # Batch-load all DB rows in one query
        db_rows: dict[str, SiteConfig] = {}
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(SiteConfig))
            for row in result.scalars().all():
                db_rows[row.source_id] = row

        # Merge for each unique source
        seen: set[str] = set()
        output: dict[str, DownloadParams] = {}
        for site in GDL_SITES:
            if site.source_id in seen:
                continue
            seen.add(site.source_id)
            output[site.source_id] = self._merge(site.source_id, db_rows.get(site.source_id))

        self._batch_cache = (output, time.time())
        return output

    # ── Pub/Sub Listener ──────────────────────────────────────────────

    async def start_listener(self) -> None:
        """Start Redis Pub/Sub listener for cross-container cache invalidation."""
        try:
            pubsub = get_redis().pubsub()
            await pubsub.subscribe(_INVALIDATION_CHANNEL)
            self._listener_task = asyncio.create_task(self._listen(pubsub), name="site_config_listener")
        except Exception:
            logger.warning("[site_config] failed to start Pub/Sub listener — cache uses TTL only")

    async def stop_listener(self) -> None:
        """Cancel the Pub/Sub listener task on shutdown."""
        if self._listener_task is not None and not self._listener_task.done():
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
            self._listener_task = None

    async def _listen(self, pubsub) -> None:
        """Listen for invalidation messages and evict cache entries."""
        try:
            async for msg in pubsub.listen():
                if msg["type"] == "message":
                    data = msg["data"]
                    source_id = data.decode() if isinstance(data, bytes) else data
                    self._cache.pop(source_id, None)
                    self._batch_cache = None
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.warning("[site_config] Pub/Sub listener died — cache uses TTL only")
        finally:
            try:
                await pubsub.unsubscribe(_INVALIDATION_CHANNEL)
                await pubsub.aclose()
            except Exception:
                pass

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
        site_defaults = get_site_config(source_id)

        # Start with _sites.py defaults
        base: dict = {
            "retries": site_defaults.retries,
            "http_timeout": site_defaults.http_timeout,
            "sleep_request": site_defaults.sleep_request,
            "concurrency": 2,  # not in GdlSiteConfig; default 2
            "inactivity_timeout": site_defaults.inactivity_timeout,
        }

        if row is not None:
            # Layer 2: adaptive (lower priority than override)
            adaptive_dl = row.adaptive.get("download", {}) if row.adaptive else {}
            for field in _DOWNLOAD_FIELDS:
                if field in adaptive_dl:
                    base[field] = adaptive_dl[field]

            # Layer 3: manual overrides (highest priority)
            override_dl = row.overrides.get("download", {}) if row.overrides else {}
            for field in _DOWNLOAD_FIELDS:
                if field in override_dl:
                    base[field] = override_dl[field]

        return DownloadParams(**base)

    @staticmethod
    def _validate_overrides(overrides: dict) -> None:
        """Validate override values before persisting."""
        dl = overrides.get("download", {})
        if "concurrency" in dl:
            c = dl["concurrency"]
            if not isinstance(c, int) or c < 1 or c > 20:
                raise ValueError(f"concurrency must be 1-20, got {c}")
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
        if "sleep_request" in dl:
            sr = dl["sleep_request"]
            if sr is not None:
                if isinstance(sr, int | float):
                    if sr <= 0 or sr > 3600:
                        raise ValueError(f"sleep_request must be 0 < value <= 3600, got {sr}")
                elif isinstance(sr, list | tuple) and len(sr) == 2:
                    if not all(isinstance(x, int | float) and 0 < x <= 3600 for x in sr):
                        raise ValueError(f"sleep_request tuple values must be 0 < value <= 3600, got {sr}")
                else:
                    raise ValueError(f"sleep_request must be float or [min, max] pair, got {type(sr).__name__}")
        if "browser_profile" in dl:
            bp = dl["browser_profile"]
            if bp is not None and bp not in ("chrome", "firefox"):
                raise ValueError("browser_profile must be 'chrome', 'firefox', or null")
        if "proxy_url" in dl:
            pu = dl["proxy_url"]
            if pu is not None and not pu.startswith(("http://", "https://", "socks5://")):
                raise ValueError("proxy_url must start with http://, https://, or socks5://")

        fm = overrides.get("field_mapping", {})
        if fm:
            _validate_field_mapping(fm)

# ── Module-level helpers ──────────────────────────────────────────────

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
