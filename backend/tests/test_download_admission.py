"""Regression tests for durable, FIFO download admission.

The database is the source of truth for source-level capacity. SAQ may deliver
the same logical job more than once, so admission must be both FIFO and fenced
by an execution token.
"""

import uuid

from db.models import DownloadJob


def _admission(session):
    from services.download_admission import DownloadAdmission

    return DownloadAdmission(session)


def test_admission_key_routes_native_and_fallback_sources():
    from services.download_admission import admission_key_for

    assert admission_key_for("ehentai", "https://e-hentai.org/g/1/token") == "ehentai"
    assert admission_key_for("pixiv", "https://www.pixiv.net/artworks/1") == "pixiv"
    assert admission_key_for("fanbox", "https://creator.fanbox.cc/posts/1") == "fanbox"
    assert admission_key_for("twitter", "https://x.com/user/status/1") == "gallery_dl:x.com"
    assert admission_key_for("weibo", "https://www.weibo.com/123") == "gallery_dl:weibo.com"
    assert admission_key_for("unknown", "https://www.example.test/gallery/1") == "gallery_dl:example.test"


async def test_two_fallback_jobs_share_hostname_fifo_before_first_delivery(db_session):
    from services.download_admission import admission_key_for

    first_key = admission_key_for("twitter", "https://x.com/user/status/1")
    second_key = admission_key_for("twitter", "https://x.com/other/status/2")
    first = await _queued_job(db_session, key=first_key, ticket=1)
    second = await _queued_job(db_session, key=second_key, ticket=2)
    admission = _admission(db_session)

    second_claim = await admission.claim(second.id, second_key, max_count=1)
    first_claim = await admission.claim(first.id, first_key, max_count=1)

    assert first_key == second_key == "gallery_dl:x.com"
    assert second_claim.acquired is False
    assert second_claim.queue_position == 2
    assert first_claim.acquired is True


async def _queued_job(session, *, key: str, ticket: int) -> DownloadJob:
    job = DownloadJob(
        id=uuid.uuid4(),
        url=f"https://example.test/{ticket}",
        source=key,
        status="queued",
        progress={},
        admission_key=key,
        admission_ticket=ticket,
    )
    session.add(job)
    await session.commit()
    return job


async def test_claim_is_strict_fifo_up_to_source_capacity(db_session):
    first = await _queued_job(db_session, key="ehentai", ticket=10)
    second = await _queued_job(db_session, key="ehentai", ticket=20)
    third = await _queued_job(db_session, key="ehentai", ticket=30)
    admission = _admission(db_session)

    out_of_order = await admission.claim(third.id, "ehentai", max_count=2)
    first_claim = await admission.claim(first.id, "ehentai", max_count=2)
    second_claim = await admission.claim(second.id, "ehentai", max_count=2)
    third_claim = await admission.claim(third.id, "ehentai", max_count=2)

    assert out_of_order.acquired is False
    assert out_of_order.queue_position == 3
    assert first_claim.acquired is True
    assert second_claim.acquired is True
    assert third_claim.acquired is False


async def test_duplicate_claim_has_exactly_one_token_owner(db_session):
    job = await _queued_job(db_session, key="pixiv", ticket=1)
    admission = _admission(db_session)

    first = await admission.claim(job.id, "pixiv", max_count=1)
    duplicate = await admission.claim(job.id, "pixiv", max_count=1)

    assert first.acquired is True
    assert first.token
    assert duplicate.acquired is False
    await db_session.refresh(job)
    assert str(job.admission_token) == str(first.token)
    assert job.status == "running"


async def test_release_is_token_fenced_against_late_execution(db_session):
    job = await _queued_job(db_session, key="fanbox", ticket=1)
    admission = _admission(db_session)
    claim = await admission.claim(job.id, "fanbox", max_count=1)

    stale_release = await admission.release(job.id, uuid.uuid4())
    await db_session.refresh(job)
    assert stale_release is False
    assert str(job.admission_token) == str(claim.token)

    owner_release = await admission.release(job.id, claim.token)
    await db_session.refresh(job)
    assert owner_release is True
    assert job.admission_token is None


async def test_different_admission_keys_do_not_block_each_other(db_session):
    eh_job = await _queued_job(db_session, key="ehentai", ticket=1)
    pixiv_job = await _queued_job(db_session, key="pixiv", ticket=2)
    next_eh_job = await _queued_job(db_session, key="ehentai", ticket=3)
    admission = _admission(db_session)

    eh_claim = await admission.claim(eh_job.id, "ehentai", max_count=1)
    pixiv_claim = await admission.claim(pixiv_job.id, "pixiv", max_count=1)
    blocked_eh = await admission.claim(next_eh_job.id, "ehentai", max_count=1)

    assert eh_claim.acquired is True
    assert pixiv_claim.acquired is True
    assert blocked_eh.acquired is False


async def test_dynamic_limit_decrease_drains_and_increase_admits(db_session):
    first = await _queued_job(db_session, key="gallery_dl:example.test", ticket=1)
    second = await _queued_job(db_session, key="gallery_dl:example.test", ticket=2)
    third = await _queued_job(db_session, key="gallery_dl:example.test", ticket=3)
    admission = _admission(db_session)

    first_claim = await admission.claim(first.id, first.admission_key, max_count=2)
    second_claim = await admission.claim(second.id, second.admission_key, max_count=2)

    # Lowering the limit never kills current owners. No new owner is admitted
    # until the holder count drops below the new limit.
    assert (await admission.claim(third.id, third.admission_key, max_count=1)).acquired is False
    await admission.release(first.id, first_claim.token)
    assert (await admission.claim(third.id, third.admission_key, max_count=1)).acquired is False

    # Raising capacity is observed by the next attempt without restarting.
    raised = await admission.claim(third.id, third.admission_key, max_count=2)
    assert raised.acquired is True
    assert second_claim.acquired is True


async def test_paused_token_owner_still_consumes_capacity(db_session):
    active = await _queued_job(db_session, key="ehentai", ticket=1)
    waiting = await _queued_job(db_session, key="ehentai", ticket=2)
    admission = _admission(db_session)
    claim = await admission.claim(active.id, "ehentai", max_count=1)

    active.status = "paused"
    await db_session.commit()

    assert claim.acquired is True
    assert (await admission.claim(waiting.id, "ehentai", max_count=1)).acquired is False


# ── Persona-aware claim (ADR 0022) ────────────────────────────────────


async def _persona(session, persona_id: int, name: str):
    from db.models import EgressPersona

    session.add(EgressPersona(id=persona_id, name=name))
    await session.commit()


def _slots(*ids: int, capacity: int = 1):
    from services.download_admission import PersonaSlot

    return [PersonaSlot(persona_id=i, name=f"p{i}", capacity=capacity) for i in ids]


async def test_persona_claim_spreads_fifo_jobs_across_personas_up_to_each_capacity(db_session):
    key = "gallery_dl:x.com#persona"
    await _persona(db_session, 11, "p11")
    await _persona(db_session, 12, "p12")
    jobs = [await _queued_job(db_session, key=key, ticket=t) for t in (1, 2, 3)]
    admission = _admission(db_session)

    c1 = await admission.claim_with_personas(jobs[0].id, key, _slots(11, 12))
    c2 = await admission.claim_with_personas(jobs[1].id, key, _slots(11, 12))
    c3 = await admission.claim_with_personas(jobs[2].id, key, _slots(11, 12))

    assert c1.acquired and c2.acquired
    assert {c1.persona_id, c2.persona_id} == {11, 12}
    assert c3.acquired is False
    assert c3.queue_position == 1


async def test_persona_claim_out_of_fifo_order_waits_even_when_a_persona_is_free(db_session):
    key = "gallery_dl:x.com#persona"
    await _persona(db_session, 11, "p11")
    first = await _queued_job(db_session, key=key, ticket=1)
    second = await _queued_job(db_session, key=key, ticket=2)

    early = await _admission(db_session).claim_with_personas(second.id, key, _slots(11))

    assert early.acquired is False
    assert early.queue_position == 2
    assert (await _admission(db_session).claim_with_personas(first.id, key, _slots(11))).acquired


async def test_persona_claim_takes_preferred_persona_when_it_has_a_free_slot(db_session):
    key = "gallery_dl:x.com#persona"
    await _persona(db_session, 11, "p11")
    await _persona(db_session, 12, "p12")
    job = await _queued_job(db_session, key=key, ticket=1)

    claim = await _admission(db_session).claim_with_personas(job.id, key, _slots(11, 12), preferred_persona_id=12)

    assert claim.persona_id == 12


async def test_persona_claim_skips_preferred_persona_without_free_slot(db_session):
    key = "gallery_dl:x.com#persona"
    await _persona(db_session, 11, "p11")
    await _persona(db_session, 12, "p12")
    a = await _queued_job(db_session, key=key, ticket=1)
    b = await _queued_job(db_session, key=key, ticket=2)
    admission = _admission(db_session)

    await admission.claim_with_personas(a.id, key, _slots(11, 12), preferred_persona_id=12)
    second = await admission.claim_with_personas(b.id, key, _slots(11, 12), preferred_persona_id=12)

    assert second.acquired is True
    assert second.persona_id == 11


async def test_persona_claim_without_candidates_keeps_job_queued_with_position(db_session):
    key = "gallery_dl:x.com#persona"
    job = await _queued_job(db_session, key=key, ticket=1)

    claim = await _admission(db_session).claim_with_personas(job.id, key, [])

    await db_session.refresh(job)
    assert claim.acquired is False
    assert claim.queue_position == 1
    assert job.status == "queued"
    assert job.admission_token is None


async def test_persona_claim_records_persona_and_name_snapshot_and_release_keeps_them(db_session):
    key = "gallery_dl:x.com#persona"
    await _persona(db_session, 11, "p11")
    job = await _queued_job(db_session, key=key, ticket=1)
    admission = _admission(db_session)

    claim = await admission.claim_with_personas(job.id, key, _slots(11))
    await admission.release(job.id, claim.token)

    await db_session.refresh(job)
    assert job.persona_id == 11
    assert job.persona_name == "p11"
    assert job.admission_token is None


async def test_persona_queue_does_not_consume_direct_site_capacity(db_session):
    persona_key = "gallery_dl:x.com#persona"
    await _persona(db_session, 11, "p11")
    persona_job = await _queued_job(db_session, key=persona_key, ticket=1)
    direct_job = await _queued_job(db_session, key="gallery_dl:x.com", ticket=2)
    admission = _admission(db_session)

    await admission.claim_with_personas(persona_job.id, persona_key, _slots(11))
    direct = await admission.claim(direct_job.id, "gallery_dl:x.com", max_count=1)

    assert direct.acquired is True
    assert direct.persona_id is None


async def test_legacy_claim_after_persona_run_clears_persona_name_but_keeps_persona_id(db_session):
    persona_key = "gallery_dl:x.com#persona"
    await _persona(db_session, 11, "p11")
    job = await _queued_job(db_session, key=persona_key, ticket=1)
    admission = _admission(db_session)

    first = await admission.claim_with_personas(job.id, persona_key, _slots(11))
    await admission.release(job.id, first.token)

    # Retry: the row goes back to queued (the token was already cleared by release).
    job.status = "queued"
    await db_session.commit()

    # Personas are now off / all disabled, so the job is claimed through the direct path.
    direct = await admission.claim(job.id, "gallery_dl:x.com", max_count=1)

    await db_session.refresh(job)
    assert direct.acquired is True
    assert direct.persona_id is None
    # persona_name is the display snapshot of the *current* run: a direct run has none.
    assert job.persona_name is None
    # persona_id stays as the sticky preference for a later persona-mode retry.
    assert job.persona_id == 11
