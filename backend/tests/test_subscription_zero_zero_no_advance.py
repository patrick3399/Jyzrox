"""Regression: 0-downloaded + 0-skipped subscription run must NOT advance
``Subscription.last_success_at``.

Real incident: sub 7 (nidemiaozai/Twitter) had ``date-after`` set from a prior
``last_success_at``. gallery-dl filter-rejected every timeline item (no skip,
no download) and returned 0/0. download.py treated this as "done", advancing
``last_success_at`` to NOW. Next renew's cutoff advanced another day,
perpetually 0/0 — death spiral.

Fix: ``_set_subscription_result(advance_success=False)`` for 0/0 runs.
"""

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_session_capture():
    """Build a fake AsyncSession that captures UPDATE .values() into ``captured``."""
    captured: dict = {}

    fake_session = AsyncMock()
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=None)

    fake_job = MagicMock()
    fake_job.subscription_id = 7
    fake_session.get = AsyncMock(return_value=fake_job)

    async def fake_execute(stmt, *_args, **_kwargs):
        captured["values"] = stmt.compile().params
        return MagicMock()

    fake_session.execute = AsyncMock(side_effect=fake_execute)
    fake_session.commit = AsyncMock()
    return fake_session, captured


@pytest.mark.asyncio
async def test_zero_zero_subscription_done_does_not_advance_last_success_at(monkeypatch):
    import core.database as cdb
    from worker import download as dl_mod

    fake_session, captured = _make_session_capture()
    monkeypatch.setattr(cdb, "AsyncSessionLocal", MagicMock(return_value=fake_session))

    db_job_id = str(uuid.uuid4())
    await dl_mod._set_subscription_result(db_job_id, "done", error=None, advance_success=False)

    assert "last_status" in captured["values"]
    assert captured["values"]["last_status"] == "done"
    # Critical: advance_success=False must NOT include last_success_at
    assert "last_success_at" not in captured["values"], (
        f"0/0 run should not advance last_success_at, got: {captured['values']}"
    )


@pytest.mark.asyncio
async def test_normal_done_still_advances_last_success_at(monkeypatch):
    """Sanity: advance_success=True (default) keeps existing behavior."""
    import core.database as cdb
    from worker import download as dl_mod

    fake_session, captured = _make_session_capture()
    monkeypatch.setattr(cdb, "AsyncSessionLocal", MagicMock(return_value=fake_session))

    db_job_id = str(uuid.uuid4())
    await dl_mod._set_subscription_result(db_job_id, "done")

    assert captured["values"]["last_status"] == "done"
    assert "last_success_at" in captured["values"]
    assert isinstance(captured["values"]["last_success_at"], datetime)
