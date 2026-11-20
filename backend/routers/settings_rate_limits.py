"""Settings: download rate limits."""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.auth import require_role
from core.config import settings as app_settings
from core.redis_client import get_redis

logger = logging.getLogger(__name__)
router = APIRouter()

_admin = require_role("admin")
_member = require_role("member")


class SiteRateConfig(BaseModel):
    concurrency: int | None = None
    delay_ms: int | None = None
    image_concurrency: int | None = None
    page_delay_ms: int | None = None
    pagination_delay_ms: int | None = None
    illust_delay_ms: int | None = None


class RateLimitSchedule(BaseModel):
    enabled: bool | None = None
    start_hour: int | None = None
    end_hour: int | None = None
    mode: str | None = None


class RateLimitSettings(BaseModel):
    sites: dict[str, SiteRateConfig] | None = None
    schedule: RateLimitSchedule | None = None


class RateLimitOverride(BaseModel):
    unlocked: bool


# ── Rate Limit Endpoints ──────────────────────────────────────────────


async def _build_rate_limit_response(redis) -> dict:
    """Read current rate limit config from Redis and return the full response dict."""

    async def _read_int(key: str, default: int) -> int:
        val = await redis.get(key)
        if val is not None:
            try:
                return int(val)
            except ValueError, TypeError:
                pass
        return default

    async def _read_str(key: str, default: str) -> str:
        val = await redis.get(key)
        if val is not None:
            if isinstance(val, bytes):
                return val.decode()
            return str(val)
        return default

    async def _read_bool(key: str, default: bool) -> bool:
        val = await redis.get(key)
        if val is not None:
            return val in (b"1", "1")
        return default

    eh_concurrency = await _read_int("rate_limit:config:ehentai:concurrency", app_settings.eh_max_concurrency)
    eh_delay_ms = await _read_int("rate_limit:config:ehentai:delay_ms", 0)
    eh_image_concurrency = await _read_int(
        "rate_limit:config:ehentai:image_concurrency", app_settings.eh_download_concurrency
    )

    pixiv_concurrency = await _read_int("rate_limit:config:pixiv:concurrency", 2)
    pixiv_page_delay = await _read_int("rate_limit:config:pixiv:page_delay_ms", 500)
    pixiv_pagination_delay = await _read_int("rate_limit:config:pixiv:pagination_delay_ms", 1000)
    pixiv_illust_delay = await _read_int("rate_limit:config:pixiv:illust_delay_ms", 2000)

    gdl_concurrency = await _read_int("rate_limit:config:gallery_dl:concurrency", 1)
    gdl_delay_ms = await _read_int("rate_limit:config:gallery_dl:delay_ms", 0)

    schedule_enabled = await _read_bool("rate_limit:schedule:enabled", False)
    schedule_start_hour = await _read_int("rate_limit:schedule:start_hour", 0)
    schedule_end_hour = await _read_int("rate_limit:schedule:end_hour", 6)
    schedule_mode = await _read_str("rate_limit:schedule:mode", "full_speed")

    override_val = await redis.get("rate_limit:override:unlocked")
    override_active = override_val is not None

    schedule_active_val = await redis.get("rate_limit:schedule:active")
    schedule_active = schedule_active_val in (b"1", "1")

    return {
        "sites": {
            "ehentai": {
                "concurrency": eh_concurrency,
                "delay_ms": eh_delay_ms,
                "image_concurrency": eh_image_concurrency,
            },
            "pixiv": {
                "concurrency": pixiv_concurrency,
                "delay_ms": None,
                "image_concurrency": None,
                "page_delay_ms": pixiv_page_delay,
                "pagination_delay_ms": pixiv_pagination_delay,
                "illust_delay_ms": pixiv_illust_delay,
            },
            "gallery_dl": {
                "concurrency": gdl_concurrency,
                "delay_ms": gdl_delay_ms,
                "image_concurrency": None,
            },
        },
        "schedule": {
            "enabled": schedule_enabled,
            "start_hour": schedule_start_hour,
            "end_hour": schedule_end_hour,
            "mode": schedule_mode,
        },
        "override_active": override_active,
        "schedule_active": schedule_active,
    }


@router.get("/rate-limits")
async def get_rate_limits(_: dict = Depends(_admin)):
    """Get current download rate limit configuration."""
    redis = get_redis()
    return await _build_rate_limit_response(redis)


@router.patch("/rate-limits")
async def patch_rate_limits(
    req: RateLimitSettings,
    _: dict = Depends(_admin),
):
    """Partially update download rate limit configuration."""
    redis = get_redis()

    def _validate_concurrency(v: int | None, field: str) -> None:
        if v is not None and not (1 <= v <= 10):
            raise HTTPException(status_code=400, detail=f"{field} must be between 1 and 10")

    def _validate_delay_ms(v: int | None, field: str) -> None:
        if v is not None and not (0 <= v <= 10000):
            raise HTTPException(status_code=400, detail=f"{field} must be between 0 and 10000")

    def _validate_hour(v: int | None, field: str) -> None:
        if v is not None and not (0 <= v <= 23):
            raise HTTPException(status_code=400, detail=f"{field} must be between 0 and 23")

    _VALID_SOURCES = {"ehentai", "pixiv", "gallery_dl"}

    if req.sites:
        for source, cfg in req.sites.items():
            if source not in _VALID_SOURCES:
                raise HTTPException(status_code=400, detail=f"Unknown source: {source}")
            _validate_concurrency(cfg.concurrency, f"{source}.concurrency")
            _validate_delay_ms(cfg.delay_ms, f"{source}.delay_ms")
            _validate_concurrency(cfg.image_concurrency, f"{source}.image_concurrency")
            _validate_delay_ms(cfg.page_delay_ms, f"{source}.page_delay_ms")
            _validate_delay_ms(cfg.pagination_delay_ms, f"{source}.pagination_delay_ms")
            _validate_delay_ms(cfg.illust_delay_ms, f"{source}.illust_delay_ms")

            if cfg.concurrency is not None:
                await redis.set(f"rate_limit:config:{source}:concurrency", str(cfg.concurrency))
            if cfg.delay_ms is not None:
                await redis.set(f"rate_limit:config:{source}:delay_ms", str(cfg.delay_ms))
            if cfg.image_concurrency is not None:
                await redis.set(f"rate_limit:config:{source}:image_concurrency", str(cfg.image_concurrency))
            if cfg.page_delay_ms is not None:
                await redis.set(f"rate_limit:config:{source}:page_delay_ms", str(cfg.page_delay_ms))
            if cfg.pagination_delay_ms is not None:
                await redis.set(f"rate_limit:config:{source}:pagination_delay_ms", str(cfg.pagination_delay_ms))
            if cfg.illust_delay_ms is not None:
                await redis.set(f"rate_limit:config:{source}:illust_delay_ms", str(cfg.illust_delay_ms))

        # Bridge writes to SiteConfigService (M1)
        from core.site_config import site_config_service

        for source, cfg in req.sites.items():
            dl_overrides: dict = {}
            if cfg.concurrency is not None:
                dl_overrides["concurrency"] = cfg.concurrency
            if cfg.delay_ms is not None:
                dl_overrides["sleep_request"] = cfg.delay_ms / 1000.0 if cfg.delay_ms > 0 else None
            if dl_overrides:
                try:
                    await site_config_service.update(source, {"download": dl_overrides})
                except Exception:
                    pass  # Redis keys still authoritative during migration

    if req.schedule:
        sched = req.schedule
        _validate_hour(sched.start_hour, "schedule.start_hour")
        _validate_hour(sched.end_hour, "schedule.end_hour")

        if sched.enabled is not None:
            await redis.set("rate_limit:schedule:enabled", "1" if sched.enabled else "0")
        if sched.start_hour is not None:
            await redis.set("rate_limit:schedule:start_hour", str(sched.start_hour))
        if sched.end_hour is not None:
            await redis.set("rate_limit:schedule:end_hour", str(sched.end_hour))
        if sched.mode is not None:
            if sched.mode not in ("full_speed", "standard"):
                raise HTTPException(status_code=400, detail="schedule.mode must be 'full_speed' or 'standard'")
            await redis.set("rate_limit:schedule:mode", sched.mode)

        # Immediately evaluate schedule_active so the response reflects the current state
        enabled_val = await redis.get("rate_limit:schedule:enabled")
        enabled = enabled_val in (b"1", "1")

        if not enabled:
            await redis.delete("rate_limit:schedule:active")
        else:
            start_val = await redis.get("rate_limit:schedule:start_hour")
            end_val = await redis.get("rate_limit:schedule:end_hour")
            try:
                start_hour = int(start_val) if start_val is not None else 0
            except ValueError, TypeError:
                start_hour = 0
            try:
                end_hour = int(end_val) if end_val is not None else 6
            except ValueError, TypeError:
                end_hour = 6

            current_hour = datetime.now(UTC).hour
            if start_hour <= end_hour:
                in_window = start_hour <= current_hour < end_hour
            else:
                in_window = current_hour >= start_hour or current_hour < end_hour

            if in_window:
                await redis.set("rate_limit:schedule:active", "1")
            else:
                await redis.delete("rate_limit:schedule:active")

    return await _build_rate_limit_response(redis)


@router.post("/rate-limits/override")
async def set_rate_limit_override(
    req: RateLimitOverride,
    _: dict = Depends(_admin),
):
    """Set or clear the rate limit boost override."""
    redis = get_redis()
    if req.unlocked:
        await redis.set("rate_limit:override:unlocked", "1")
    else:
        await redis.delete("rate_limit:override:unlocked")
    # The download dashboard serves a 3s cached snapshot that embeds boost_mode;
    # drop it so the next read reflects this toggle instead of the old state.
    await redis.delete("dashboard:snapshot")
    return {"override_active": req.unlocked}
