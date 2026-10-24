"""Worker wiring for persona jobs (ADR 0022)."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from db.models import DownloadJob


class _FakeSession:
    async def __aenter__(self):
        return MagicMock()

    async def __aexit__(self, *exc):
        return False


def test_serialized_job_exposes_persona_name_snapshot():
    from services.download_presenter import serialize_download_job

    job = DownloadJob(id=uuid.uuid4(), url="u", status="running", progress={}, persona_name="gw12")
    assert serialize_download_job(job)["persona"] == "gw12"


async def test_download_job_waits_on_persona_cooldown_with_long_redelivery():
    import worker.download as wd
    from services.download_admission import AdmissionClaim
    from services.egress_persona import SlotDecision

    plugin = MagicMock()
    plugin.meta.source_id = "gallery_dl"
    plugin.meta.semaphore_key = None
    params = MagicMock(concurrency=1, spread_personas=True)
    decision = SlotDecision(
        claim=AdmissionClaim(acquired=False, queue_position=1),
        key="gallery_dl:x.com#persona",
        personas_cooling=True,
        persona_mode=True,
    )
    with (
        patch("plugins.registry.plugin_registry.get_handler", AsyncMock(return_value=plugin)),
        patch("core.site_config.site_config_service.get_effective_download_params", AsyncMock(return_value=params)),
        patch("services.egress_persona.claim_download_slot", AsyncMock(return_value=decision)),
        patch.object(wd, "_set_job_progress", AsyncMock()) as progress,
        patch.object(wd, "_enqueue_admission_redelivery", AsyncMock()) as redeliver,
        # download_job imports AsyncSessionLocal from core.database at call time.
        patch("core.database.AsyncSessionLocal", lambda: _FakeSession()),
    ):
        out = await wd.download_job({}, "https://x.com/a/media", db_job_id=str(uuid.uuid4()))

    assert out["status"] == "queued"
    assert progress.await_args.args[1]["wait_reason"] == "persona_cooldown"
    assert progress.await_args.args[1]["semaphore_key"] == "gallery_dl:x.com#persona"
    assert redeliver.await_args.kwargs["delay_seconds"] == 60


@pytest.mark.parametrize(("persona_mode", "expected_persona_id"), [(True, 12), (False, None)])
async def test_download_job_runs_as_persona_only_when_claim_decision_is_persona_mode(persona_mode, expected_persona_id):
    """The decision (derived from the row's stored key), not the live site switch, picks the run identity."""
    import worker.download as wd
    from services.download_admission import AdmissionClaim
    from services.egress_persona import SlotDecision

    plugin = MagicMock()
    plugin.meta.source_id = "gallery_dl"
    plugin.meta.semaphore_key = None
    # The live switch is on in both cases; only the claim decision may matter.
    params = MagicMock(concurrency=1, spread_personas=True)
    token = uuid.uuid4()
    decision = SlotDecision(
        claim=AdmissionClaim(acquired=True, token=token, queue_position=1, persona_id=12),
        key="gallery_dl:x.com#persona" if persona_mode else "gallery_dl:x.com",
        personas_cooling=False,
        persona_mode=persona_mode,
    )
    admission = MagicMock()
    admission.release = AsyncMock(return_value=False)
    with (
        patch("plugins.registry.plugin_registry.get_handler", AsyncMock(return_value=plugin)),
        patch("core.site_config.site_config_service.get_effective_download_params", AsyncMock(return_value=params)),
        patch("services.egress_persona.claim_download_slot", AsyncMock(return_value=decision)),
        patch.object(wd, "_set_job_status", AsyncMock(return_value=True)),
        patch.object(wd, "_run_download_job", AsyncMock(return_value={"status": "done"})) as run,
        patch.object(wd, "DownloadAdmission", return_value=admission),
        patch("core.database.AsyncSessionLocal", lambda: _FakeSession()),
    ):
        out = await wd.download_job({}, "https://x.com/a/media", db_job_id=str(uuid.uuid4()))

    assert out["status"] == "done"
    assert run.await_args.kwargs["persona_id"] == expected_persona_id
