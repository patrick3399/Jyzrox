"""Scheduled EhTag translation sync job."""

import logging

from worker.helpers import _cron_record, _cron_should_run

logger = logging.getLogger(__name__)


async def ehtag_sync_job(ctx: dict) -> dict:
    """Sync EhTag translations from CDN on schedule.

    Also runs on first boot (when last_run is None) to ensure
    translations are available immediately after installation.
    """
    task_id = "ehtag_sync"

    # On first boot (no last_run), always run regardless of cron schedule
    r = ctx["redis"]
    first_boot = await r.get(f"cron:{task_id}:last_run") is None

    if not first_boot and not await _cron_should_run(ctx, task_id, "0 4 * * 0"):
        return {"status": "skipped"}

    await _cron_record(ctx, task_id, "running")
    try:
        from services.ehtag_importer import import_ehtag_translations
        count = await import_ehtag_translations()
        logger.info("[ehtag_sync] Imported %d translations", count)
        await _cron_record(ctx, task_id, "ok")
        from core.events import EventType, emit_safe
        await emit_safe(EventType.EHTAG_SYNC_COMPLETED, resource_type="system", count=count)
        return {"status": "ok", "count": count}
    except Exception as exc:
        logger.error("[ehtag_sync] Failed: %s", exc)
        await _cron_record(ctx, task_id, "error", str(exc))
        return {"status": "error", "error": str(exc)}
