"""Subscription serialization helpers shared by the subscription routers."""

import core.redis_client
from db.models import Gallery
from services.subscription_pause import check_lock_key


def serialize_subscription(s, gallery: Gallery | None = None, checking: bool = False) -> dict:
    data = {
        "id": s.id,
        "name": s.name,
        "url": s.url,
        "source": s.source,
        "source_id": s.source_id,
        "avatar_url": s.avatar_url,
        "enabled": s.enabled,
        "auto_download": s.auto_download,
        "cron_expr": s.cron_expr,
        "group_id": s.group_id,
        "download_options": s.download_options or {},
        "last_checked_at": s.last_checked_at.isoformat() if s.last_checked_at else None,
        "last_item_id": s.last_item_id,
        "last_status": s.last_status,
        "last_error": s.last_error,
        "last_job_id": str(s.last_job_id) if s.last_job_id else None,
        "next_check_at": s.next_check_at.isoformat() if s.next_check_at else None,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "paused_at": s.paused_at.isoformat() if s.paused_at else None,
        "paused_reason": s.paused_reason,
        "paused_until": s.paused_until.isoformat() if s.paused_until else None,
        "checking": checking,
    }
    if gallery:
        data["gallery_id"] = gallery.id
        data["gallery_source"] = gallery.source
        data["gallery_source_id"] = gallery.source_id
        data["gallery_title"] = gallery.title
    return data


async def checking_flags(sub_ids: list[int]) -> list[bool]:
    """Per-subscription check-lock state; Redis is best-effort here."""
    if not sub_ids:
        return []
    try:
        locks = list(await core.redis_client.get_redis().mget([check_lock_key(i) for i in sub_ids]))
    except Exception:
        locks = []
    if len(locks) != len(sub_ids):
        locks = [None] * len(sub_ids)
    return [lock is not None for lock in locks]
