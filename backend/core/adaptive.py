"""Adaptive engine — v3.0.

Tracks per-source credential health signals in Redis and persists warnings to
PostgreSQL.  Sleep multipliers and timeout tuning removed in v3; those
responsibilities moved to the download worker directly.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import Enum

logger = logging.getLogger(__name__)

# ── Compiled regex patterns ────────────────────────────────────────────

_RE_403 = re.compile(r"HTTP Error 403|403 Forbidden", re.IGNORECASE)


# ── Data models ───────────────────────────────────────────────────────


class AdaptiveSignal(str, Enum):
    HTTP_403 = "http_403"
    HTML_RESPONSE = "html_response"


@dataclass
class AdaptiveState:
    credential_warning: bool = False
    last_signal: str | None = None
    last_signal_at: str | None = None

    @staticmethod
    def from_dict(data: dict) -> AdaptiveState:
        """Reconstruct AdaptiveState from JSON dict, safely coercing types."""
        try:
            return AdaptiveState(
                credential_warning=bool(data.get("credential_warning", False)),
                last_signal=data.get("last_signal") or None,
                last_signal_at=data.get("last_signal_at") or None,
            )
        except (ValueError, TypeError, AttributeError):
            return AdaptiveState()


# ── AdaptiveEngine ────────────────────────────────────────────────────

_ADAPTIVE_TTL = 86400  # 24 hours
_MAX_PERSIST_PER_RUN = 200


class AdaptiveEngine:
    """Redis-backed adaptive state manager.

    Hot path: all mutations are atomic Lua scripts (single round-trip).
    Cold path: persist_dirty() flushes changed states to PostgreSQL every 5 min.
    """

    _DIRTY_KEY = "adaptive:dirty"

    # Lua: atomic read-modify-write for credential signals only.
    # KEYS[1] = adaptive:{source_id}
    # ARGV[1] = source_id (for dirty tracking)
    # ARGV[2] = signal string
    # ARGV[3] = TTL seconds
    # ARGV[4] = now ISO string
    _SIGNAL_LUA = """
local key = KEYS[1]
local source_id = ARGV[1]
local signal = ARGV[2]
local ttl = tonumber(ARGV[3])
local now_str = ARGV[4]
local dirty_key = "adaptive:dirty"

local raw = redis.call('GET', key)
local state
if raw then
    state = cjson.decode(raw)
else
    state = {credential_warning = false, last_signal = false, last_signal_at = false}
end

if signal == 'http_403' or signal == 'html_response' then
    state['credential_warning'] = true
end

state['last_signal'] = signal
state['last_signal_at'] = now_str

local new_raw = cjson.encode(state)
redis.call('SET', key, new_raw, 'EX', ttl)
redis.call('SADD', dirty_key, source_id)
return new_raw
"""

    @staticmethod
    def _parse_raw(raw: bytes | str) -> AdaptiveState:
        """Parse raw Redis response into AdaptiveState."""
        if isinstance(raw, bytes):
            raw = raw.decode()
        try:
            return AdaptiveState.from_dict(json.loads(raw))
        except (json.JSONDecodeError, TypeError):
            return AdaptiveState()

    async def record_signal(self, source_id: str, signal: AdaptiveSignal) -> AdaptiveState:
        """Record a signal using Lua script for atomic read-modify-write."""
        from core.redis_client import get_redis

        r = get_redis()
        key = f"adaptive:{source_id}"
        now_str = datetime.now(UTC).isoformat()
        raw = await r.eval(
            self._SIGNAL_LUA,
            1,
            key,
            source_id,
            signal.value,
            str(_ADAPTIVE_TTL),
            now_str,
        )
        return self._parse_raw(raw)

    async def get_state(self, source_id: str) -> AdaptiveState:
        """GET key → parse JSON, fallback to DB, then default AdaptiveState."""
        from core.redis_client import get_redis

        r = get_redis()
        raw = await r.get(f"adaptive:{source_id}")
        if raw:
            return self._parse_raw(raw)

        # Fallback: load from DB (covers Redis restart before worker startup)
        try:
            from core.database import AsyncSessionLocal
            from db.models import SiteConfig

            async with AsyncSessionLocal() as session:
                row = await session.get(SiteConfig, source_id)
            if row and row.adaptive:
                cw = row.adaptive.get("credential_warning", False)
                if cw:
                    state = AdaptiveState(credential_warning=True)
                    # Re-populate Redis for subsequent reads
                    await r.set(
                        f"adaptive:{source_id}",
                        json.dumps(asdict(state)),
                        ex=_ADAPTIVE_TTL,
                    )
                    return state
        except Exception:
            pass

        return AdaptiveState()

    async def get_states_batch(self, source_ids: list[str]) -> dict[str, AdaptiveState]:
        """Batch GET all source adaptive states in a single pipeline."""
        if not source_ids:
            return {}
        from core.redis_client import get_redis

        r = get_redis()
        pipe = r.pipeline(transaction=False)
        for sid in source_ids:
            pipe.get(f"adaptive:{sid}")
        raw_list = await pipe.execute()
        return {
            sid: self._parse_raw(raw) if raw else AdaptiveState()
            for sid, raw in zip(source_ids, raw_list, strict=False)
        }

    async def reset(self, source_id: str) -> None:
        """DEL key + SREM from dirty set."""
        from core.redis_client import get_redis

        r = get_redis()
        pipe = r.pipeline(transaction=False)
        pipe.delete(f"adaptive:{source_id}")
        pipe.srem(self._DIRTY_KEY, source_id)
        await pipe.execute()

    async def persist_dirty(self) -> int:
        """SPOP dirty set → upsert to DB. Max 200 per run."""
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from core.database import AsyncSessionLocal
        from core.redis_client import get_redis
        from db.models import SiteConfig

        r = get_redis()

        # SPOP up to _MAX_PERSIST_PER_RUN items in one call
        raw_items = await r.spop(self._DIRTY_KEY, _MAX_PERSIST_PER_RUN)
        if not raw_items:
            return 0
        items = raw_items if isinstance(raw_items, list) else [raw_items]

        persisted = 0
        failed: list[str] = []

        # Batch all upserts in one session
        async with AsyncSessionLocal() as session:
            for raw_sid in items:
                source_id = raw_sid.decode() if isinstance(raw_sid, bytes) else raw_sid
                try:
                    state = await self.get_state(source_id)
                    stmt = (
                        pg_insert(SiteConfig)
                        .values(
                            source_id=source_id,
                            overrides={},
                            adaptive={"credential_warning": state.credential_warning},
                        )
                        .on_conflict_do_update(
                            index_elements=["source_id"],
                            set_={"adaptive": {"credential_warning": state.credential_warning}},
                        )
                    )
                    await session.execute(stmt)
                    persisted += 1
                except Exception as exc:
                    logger.warning("[adaptive] persist_dirty failed for %s: %s", source_id, exc)
                    failed.append(source_id)

            if persisted:
                await session.commit()

        # Put failed items back so they retry next run
        if failed:
            try:
                await r.sadd(self._DIRTY_KEY, *failed)
            except Exception as exc:
                logger.warning("[adaptive] failed to re-add dirty items: %s", exc)

        return persisted

    async def load_all_from_db(self) -> int:
        """Startup: bulk load adaptive states from DB → Redis."""
        from sqlalchemy import select

        from core.database import AsyncSessionLocal
        from core.redis_client import get_redis
        from db.models import SiteConfig

        loaded = 0
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(SiteConfig).where(SiteConfig.adaptive != {}))
            rows = list(result.scalars().all())

        if not rows:
            return 0

        r = get_redis()
        pipe = r.pipeline(transaction=False)
        for row in rows:
            cw = row.adaptive.get("credential_warning", False) if row.adaptive else False
            state = AdaptiveState(credential_warning=bool(cw))
            pipe.set(f"adaptive:{row.source_id}", json.dumps(asdict(state)), ex=_ADAPTIVE_TTL)
            loaded += 1

        if loaded:
            await pipe.execute()

        return loaded


# ── Singleton ─────────────────────────────────────────────────────────

adaptive_engine = AdaptiveEngine()
