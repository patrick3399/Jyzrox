"""Persona selection, credential swap and cooldown (ADR 0022)."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from db.models import Credential, DownloadJob, EgressPersona, PersonaAccount


def _redis(cooling: set[str] | None = None):
    r = MagicMock()
    r.mget = AsyncMock(side_effect=lambda keys: [b"1" if k in (cooling or set()) else None for k in keys])
    r.set = AsyncMock()
    return r


async def _seed(session, *personas: tuple[int, str, bool]):
    for pid, name, enabled in personas:
        session.add(EgressPersona(id=pid, name=name, enabled=enabled))
    await session.commit()


async def _job(
    session,
    *,
    canonical: str,
    persona_id: int | None = None,
    admission_key: str | None = None,
    admission_ticket: int | None = None,
) -> DownloadJob:
    job = DownloadJob(
        id=uuid.uuid4(),
        url=canonical,
        canonical_url=canonical,
        status="queued",
        progress={},
        persona_id=persona_id,
        admission_key=admission_key,
        admission_ticket=admission_ticket,
    )
    session.add(job)
    await session.commit()
    return job


async def test_claim_slot_without_enabled_personas_uses_legacy_key(db_session):
    from services.egress_persona import claim_download_slot

    await _seed(db_session, (11, "p11", False))
    job = await _job(db_session, canonical="https://x.com/a", admission_key="gallery_dl:x.com#persona")
    with patch("services.egress_persona.get_redis", return_value=_redis()):
        decision = await claim_download_slot(
            db_session,
            job_id=str(job.id),
            base_key="gallery_dl:x.com",
            site_source_id="twitter",
            capacity=1,
        )
    assert decision.key == "gallery_dl:x.com"
    assert decision.claim.acquired is True
    assert decision.claim.persona_id is None


async def test_site_with_accounts_only_admits_personas_with_a_bound_account(db_session):
    from services.egress_persona import claim_download_slot

    await _seed(db_session, (11, "p11", True), (12, "p12", True))
    db_session.add(Credential(source="twitter", account="alt1", credential_type="cookies", is_active=True))
    await db_session.commit()
    db_session.add(PersonaAccount(persona_id=12, source="twitter", account="alt1"))
    await db_session.commit()
    job = await _job(db_session, canonical="https://x.com/a", admission_key="gallery_dl:x.com#persona")
    with patch("services.egress_persona.get_redis", return_value=_redis()):
        decision = await claim_download_slot(
            db_session,
            job_id=str(job.id),
            base_key="gallery_dl:x.com",
            site_source_id="twitter",
            capacity=1,
        )
    assert decision.key == "gallery_dl:x.com#persona"
    assert decision.claim.persona_id == 12
    assert decision.persona_mode is True


async def test_site_without_accounts_admits_every_enabled_persona_anonymously(db_session):
    from services.egress_persona import claim_download_slot

    await _seed(db_session, (11, "p11", True), (12, "p12", True))
    a = await _job(
        db_session,
        canonical="https://danbooru.donmai.us/posts?tags=a",
        admission_key="gallery_dl:danbooru.donmai.us#persona",
    )
    b = await _job(
        db_session,
        canonical="https://danbooru.donmai.us/posts?tags=b",
        admission_key="gallery_dl:danbooru.donmai.us#persona",
    )
    with patch("services.egress_persona.get_redis", return_value=_redis()):
        da = await claim_download_slot(
            db_session,
            job_id=str(a.id),
            base_key="gallery_dl:danbooru.donmai.us",
            site_source_id="danbooru",
            capacity=1,
        )
        db = await claim_download_slot(
            db_session,
            job_id=str(b.id),
            base_key="gallery_dl:danbooru.donmai.us",
            site_source_id="danbooru",
            capacity=1,
        )
    assert {da.claim.persona_id, db.claim.persona_id} == {11, 12}


async def test_cooling_persona_is_skipped_and_all_cooling_waits(db_session):
    from services.egress_persona import claim_download_slot, cooldown_key

    await _seed(db_session, (11, "p11", True), (12, "p12", True))
    a = await _job(
        db_session, canonical="https://danbooru.donmai.us/1", admission_key="gallery_dl:danbooru.donmai.us#persona"
    )
    redis = _redis({cooldown_key(11, "danbooru")})
    with patch("services.egress_persona.get_redis", return_value=redis):
        decision = await claim_download_slot(
            db_session,
            job_id=str(a.id),
            base_key="gallery_dl:danbooru.donmai.us",
            site_source_id="danbooru",
            capacity=1,
        )
    assert decision.claim.persona_id == 12

    b = await _job(
        db_session, canonical="https://danbooru.donmai.us/2", admission_key="gallery_dl:danbooru.donmai.us#persona"
    )
    redis = _redis({cooldown_key(11, "danbooru"), cooldown_key(12, "danbooru")})
    with patch("services.egress_persona.get_redis", return_value=redis):
        waiting = await claim_download_slot(
            db_session,
            job_id=str(b.id),
            base_key="gallery_dl:danbooru.donmai.us",
            site_source_id="danbooru",
            capacity=1,
        )
    assert waiting.claim.acquired is False
    assert waiting.personas_cooling is True


async def test_redis_error_counts_as_nothing_cooling(db_session):
    from redis.exceptions import RedisError

    from services.egress_persona import claim_download_slot

    await _seed(db_session, (11, "p11", True))
    job = await _job(
        db_session, canonical="https://danbooru.donmai.us/1", admission_key="gallery_dl:danbooru.donmai.us#persona"
    )
    broken = MagicMock()
    broken.mget = AsyncMock(side_effect=RedisError("down"))
    with patch("services.egress_persona.get_redis", return_value=broken):
        decision = await claim_download_slot(
            db_session,
            job_id=str(job.id),
            base_key="gallery_dl:danbooru.donmai.us",
            site_source_id="danbooru",
            capacity=1,
        )
    assert decision.claim.persona_id == 11


async def test_redownload_of_same_canonical_url_prefers_its_previous_persona(db_session):
    from services.egress_persona import claim_download_slot

    await _seed(db_session, (11, "p11", True), (12, "p12", True))
    old = await _job(db_session, canonical="https://danbooru.donmai.us/x", persona_id=12)
    old.status = "done"
    await db_session.commit()
    new = await _job(
        db_session, canonical="https://danbooru.donmai.us/x", admission_key="gallery_dl:danbooru.donmai.us#persona"
    )
    with patch("services.egress_persona.get_redis", return_value=_redis()):
        decision = await claim_download_slot(
            db_session,
            job_id=str(new.id),
            base_key="gallery_dl:danbooru.donmai.us",
            site_source_id="danbooru",
            capacity=1,
        )
    assert decision.claim.persona_id == 12


async def test_job_stamped_with_base_key_stays_legacy_even_if_switch_is_now_on(db_session):
    """The stored admission_key decides persona mode, not the live site switch.

    A row stamped before the switch was turned on sits in the base-key FIFO; the
    claim must keep it there instead of re-stamping it into the persona queue.
    """
    from services.egress_persona import claim_download_slot

    await _seed(db_session, (11, "p11", True))
    job = await _job(db_session, canonical="https://x.com/a", admission_key="gallery_dl:x.com")
    with patch("services.egress_persona.get_redis", return_value=_redis()):
        decision = await claim_download_slot(
            db_session,
            job_id=str(job.id),
            base_key="gallery_dl:x.com",
            site_source_id="twitter",
            capacity=1,
        )
    assert decision.key == "gallery_dl:x.com"
    assert decision.persona_mode is False
    assert decision.claim.acquired is True
    assert decision.claim.persona_id is None


async def test_persona_fifo_holds_when_newer_job_claims_first(db_session):
    """Regression: jobs are stamped with the persona key at write time, so an older
    row is already in the persona FIFO when a newer job reaches its claim first.

    Stamped with the base key, the older rows were invisible to the persona-key
    queue and the two newest jobs claimed both slots (found by a Postgres drill).
    """
    from services.egress_persona import claim_download_slot

    base_key = "gallery_dl:danbooru.donmai.us"
    await _seed(db_session, (11, "p11", True), (12, "p12", True))
    jobs = [
        await _job(
            db_session,
            canonical=f"https://danbooru.donmai.us/posts?tags={n}",
            admission_key=f"{base_key}#persona",
            admission_ticket=n,
        )
        for n in (1, 2, 3, 4)
    ]
    decisions = {}
    with patch("services.egress_persona.get_redis", return_value=_redis()):
        for n in (4, 3, 2, 1):  # newest first: delivery order differs from FIFO order
            decisions[n] = await claim_download_slot(
                db_session,
                job_id=str(jobs[n - 1].id),
                base_key=base_key,
                site_source_id="danbooru",
                capacity=1,
            )

    acquired = {n for n, d in decisions.items() if d.claim.acquired}
    assert acquired == {1, 2}
    assert decisions[1].claim.persona_id != decisions[2].claim.persona_id
    assert {decisions[1].claim.persona_id, decisions[2].claim.persona_id} == {11, 12}
    assert all(d.key == f"{base_key}#persona" for d in decisions.values())
    assert all(d.persona_mode is True for d in decisions.values())


async def test_resolve_admission_key_stamps_persona_key_only_for_manual_jobs_on_spread_sites():
    """Persist the final queue key at write time so the persona FIFO sees every row."""
    from core.site_config import DownloadParams
    from services.egress_persona import resolve_admission_key

    def _switch(spread: bool):
        return patch(
            "core.site_config.site_config_service.get_effective_download_params",
            AsyncMock(return_value=DownloadParams(spread_personas=spread)),
        )

    with _switch(True):
        # Manual gallery-dl job on a spread site queues apart from the direct queue.
        assert (
            await resolve_admission_key("twitter", "https://x.com/user/media", subscription_id=None)
            == "gallery_dl:x.com#persona"
        )
        assert (
            await resolve_admission_key("twitter", "https://www.x.com/user/media", subscription_id=None)
            == "gallery_dl:x.com#persona"
        )
        # Subscription runs never use persona mode.
        assert (
            await resolve_admission_key("twitter", "https://x.com/user/media", subscription_id=7) == "gallery_dl:x.com"
        )
        # Native sources are not gallery-dl jobs, whatever their site switch says.
        assert (
            await resolve_admission_key("ehentai", "https://e-hentai.org/g/123/abc/", subscription_id=None) == "ehentai"
        )
        assert await resolve_admission_key("pixiv", "https://www.pixiv.net/artworks/1", subscription_id=None) == "pixiv"

    with _switch(False):
        assert (
            await resolve_admission_key("twitter", "https://x.com/user/media", subscription_id=None)
            == "gallery_dl:x.com"
        )


async def test_prepare_persona_run_swaps_site_credential_for_bound_account():
    from services.credential import ActiveCredential
    from services.egress_persona import PersonaIdentity, prepare_persona_run

    identity = PersonaIdentity(12, "p12", "http://egress-12:8888", None, "firefox", "alt1")
    with (
        patch("services.egress_persona._load_identity", AsyncMock(return_value=identity)),
        patch(
            "services.egress_persona.get_account_credential",
            AsyncMock(return_value=ActiveCredential(account="alt1", value='{"auth_token": "b"}')),
        ),
    ):
        ident, creds, accounts = await prepare_persona_run(
            12, "twitter", {"twitter": '{"auth_token": "a"}', "pixiv": "rt"}, {"twitter": "main", "pixiv": "default"}
        )
    assert creds == {"twitter": '{"auth_token": "b"}', "pixiv": "rt"}
    assert accounts == {"twitter": "alt1", "pixiv": "default"}
    assert ident.network_options() == {
        "proxy_url": "http://egress-12:8888",
        "user_agent": None,
        "browser_profile": "firefox",
    }


async def test_prepare_persona_run_without_binding_drops_the_active_account():
    from services.egress_persona import PersonaIdentity, prepare_persona_run

    identity = PersonaIdentity(11, "p11", "http://egress-11:8888", None, None, None)
    with patch("services.egress_persona._load_identity", AsyncMock(return_value=identity)):
        _, creds, accounts = await prepare_persona_run(11, "danbooru", {"danbooru": "x"}, {"danbooru": "main"})
    assert "danbooru" not in creds
    assert "danbooru" not in accounts


async def test_prepare_persona_run_fails_when_bound_credential_is_missing_or_expired():
    from services.egress_persona import PersonaIdentity, PersonaUnavailable, prepare_persona_run

    identity = PersonaIdentity(12, "p12", None, None, None, "alt1")
    with (
        patch("services.egress_persona._load_identity", AsyncMock(return_value=identity)),
        patch("services.egress_persona.get_account_credential", AsyncMock(return_value=None)),
        pytest.raises(PersonaUnavailable),
    ):
        await prepare_persona_run(12, "twitter", {}, {})


def test_throttle_signal_reads_gallery_dl_diagnostics():
    from services.egress_persona import throttle_signal

    assert throttle_signal({"throttle_signals": ["http_429"]}) == "http_429"
    assert throttle_signal({"throttle_signals": ["http_403", "http_429"]}) == "http_403"
    assert throttle_signal({}) is None


def test_persona_fields_reject_both_browser_and_user_agent():
    from services.egress_persona import validate_persona_fields

    with pytest.raises(ValueError, match="either"):
        validate_persona_fields(proxy_url=None, user_agent="UA", browser_profile="chrome")
    with pytest.raises(ValueError, match="SOCKS"):
        validate_persona_fields(proxy_url="socks5://x:1", user_agent=None, browser_profile=None)
