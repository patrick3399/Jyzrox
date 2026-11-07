"""Admission redeliveries must not log at INFO (ADR 0031).

~630 waiting downloads were redelivered every 5 s, and each execution logged
`[download] url=` before checking for a slot: 170,949 lines/day for 644 downloads.
"""

import logging
import uuid
from unittest.mock import AsyncMock, MagicMock, patch


class _FakeSession:
    async def __aenter__(self):
        return MagicMock()

    async def __aexit__(self, *exc):
        return False


async def test_download_job_waiting_for_slot_logs_nothing_at_info(caplog):
    import worker.download as wd
    from services.download_admission import AdmissionClaim
    from services.egress_persona import SlotDecision

    plugin = MagicMock()
    plugin.meta.source_id = "fanbox"
    plugin.meta.semaphore_key = None
    params = MagicMock(concurrency=1, spread_personas=False)
    decision = SlotDecision(
        claim=AdmissionClaim(acquired=False, queue_position=3),
        key="fanbox",
        personas_cooling=False,
        persona_mode=False,
    )
    caplog.set_level(logging.DEBUG)
    with (
        patch("plugins.registry.plugin_registry.get_handler", AsyncMock(return_value=plugin)),
        patch("core.site_config.site_config_service.get_effective_download_params", AsyncMock(return_value=params)),
        patch("services.egress_persona.claim_download_slot", AsyncMock(return_value=decision)),
        patch.object(wd, "_set_job_progress", AsyncMock()),
        patch.object(wd, "_enqueue_admission_redelivery", AsyncMock()),
        patch("core.database.AsyncSessionLocal", lambda: _FakeSession()),
    ):
        out = await wd.download_job({}, "https://www.fanbox.cc/@a/posts/1", db_job_id=str(uuid.uuid4()))

    assert out["status"] == "queued"
    noisy = [r.getMessage() for r in caplog.records if r.levelno >= logging.INFO]
    assert noisy == []
