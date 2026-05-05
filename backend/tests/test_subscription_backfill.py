"""Regression: backfill flow must (1) enqueue with force_full_scan=True and
without last_completed_at; (2) configure gallery-dl with abort:100 and no
date-after.

User scenario: sub 7's first download was interrupted (Twitter rate-limit),
only 51/N images saved. Incremental Renew (date-after) can never reach the
older missing posts. Backfill bypasses date-after but keeps archive check —
items already in the PG ``twitter`` table (deleted-locally-by-user) are still
skipped, so this is safe.
"""

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _build_session_stub(monkeypatch, sub_mod):
    fake_session = AsyncMock()
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=None)
    fake_session.execute = AsyncMock(
        return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=None),
            scalar_one=MagicMock(return_value=None),
        )
    )
    fake_session.add = MagicMock()
    fake_session.commit = AsyncMock()
    monkeypatch.setattr(sub_mod, "AsyncSessionLocal", MagicMock(return_value=fake_session))
    return fake_session


def _make_sub():
    sub = MagicMock()
    sub.id = 7
    sub.user_id = 1
    sub.url = "https://x.com/foo"
    sub.source = "twitter"
    sub.last_success_at = datetime(2026, 5, 5, 2, 51, 5, tzinfo=UTC)
    return sub


# ── enqueue layer: force_full_scan must reach options correctly ─────────


@pytest.mark.asyncio
async def test_enqueue_for_subscription_force_full_scan_omits_last_completed_at(monkeypatch):
    """Force mode must drop last_completed_at so source.py won't set date-after."""
    from worker import subscription as sub_mod

    captured: dict = {}

    async def fake_enqueue(_name, **kw):
        captured["kwargs"] = kw
        json.dumps(kw)  # SAQ JSON serialization probe — must not raise
        return MagicMock()

    monkeypatch.setattr(sub_mod.core.queue, "enqueue", fake_enqueue)
    monkeypatch.setattr(sub_mod, "acquire_lock", AsyncMock(return_value="lock-1"))
    monkeypatch.setattr(sub_mod, "release_lock", AsyncMock())
    monkeypatch.setattr("services.source_health.is_source_enabled", AsyncMock(return_value=True))

    fake_redis = MagicMock()
    monkeypatch.setattr("core.redis_client.get_redis", MagicMock(return_value=fake_redis))
    monkeypatch.setattr("core.redis_client.publish_job_event", AsyncMock())

    _build_session_stub(monkeypatch, sub_mod)

    ctx = {"redis": fake_redis}
    result = await sub_mod._enqueue_for_subscription(ctx, _make_sub(), force_full_scan=True)

    assert result["status"] == "ok"
    options = captured["kwargs"]["options"]
    # Force mode must NOT propagate last_completed_at — that would re-enable date-after
    assert "last_completed_at" not in options
    assert options.get("force_full_scan") is True
    assert options["job_context"] == "subscription"


@pytest.mark.asyncio
async def test_enqueue_for_subscription_normal_mode_unchanged(monkeypatch):
    """Default mode (no force) keeps existing behavior: last_completed_at as iso, no force_full_scan."""
    from worker import subscription as sub_mod

    captured: dict = {}

    async def fake_enqueue(_name, **kw):
        captured["kwargs"] = kw
        json.dumps(kw)
        return MagicMock()

    monkeypatch.setattr(sub_mod.core.queue, "enqueue", fake_enqueue)
    monkeypatch.setattr(sub_mod, "acquire_lock", AsyncMock(return_value="lock-1"))
    monkeypatch.setattr(sub_mod, "release_lock", AsyncMock())
    monkeypatch.setattr("services.source_health.is_source_enabled", AsyncMock(return_value=True))

    fake_redis = MagicMock()
    monkeypatch.setattr("core.redis_client.get_redis", MagicMock(return_value=fake_redis))
    monkeypatch.setattr("core.redis_client.publish_job_event", AsyncMock())

    _build_session_stub(monkeypatch, sub_mod)

    ctx = {"redis": fake_redis}
    await sub_mod._enqueue_for_subscription(ctx, _make_sub())

    options = captured["kwargs"]["options"]
    assert "last_completed_at" in options
    assert isinstance(options["last_completed_at"], str)
    assert options.get("force_full_scan", False) is False


# ── source.py layer: force flag flips abort + drops date-after ──────────


@pytest.fixture
def mock_site_config_service():
    """Prevent _build_gallery_dl_config from querying real DB / Redis."""
    from tests.helpers import make_mock_site_config_svc

    svc = make_mock_site_config_svc()
    mock_pipeline = MagicMock()
    mock_pipeline.get = MagicMock()
    mock_pipeline.execute = AsyncMock(return_value=[])
    mock_redis = MagicMock()
    mock_redis.pipeline = MagicMock(return_value=mock_pipeline)
    mock_redis.get = AsyncMock(return_value=None)
    with (
        patch("core.site_config.site_config_service", svc),
        patch("core.redis_client.get_redis", return_value=mock_redis),
    ):
        yield svc


@pytest.fixture
def mock_config_path(tmp_path):
    """Mock settings used by _build_gallery_dl_config."""
    config_file = tmp_path / "gallery-dl.json"
    with patch("plugins.builtin.gallery_dl.source.settings") as mock_settings:
        mock_settings.data_gallery_path = str(tmp_path / "gallery")
        mock_settings.gallery_dl_config = str(config_file)
        mock_settings.gdl_archive_dsn = "postgresql://test:test@localhost:5432/test"
        yield config_file


@pytest.mark.asyncio
async def test_build_config_force_full_scan_uses_abort_100_and_no_date_after(
    mock_site_config_service, mock_config_path
):
    """Force mode in source.py: skip=abort:100, no date-after key."""
    from plugins.builtin.gallery_dl.source import _build_gallery_dl_config

    await _build_gallery_dl_config(
        credentials={},
        config_id=None,
        job_context="subscription",
        last_completed_at=None,
        force_full_scan=True,
    )

    cfg = json.loads(mock_config_path.read_text())

    assert cfg["extractor"]["archive-mode"] == "memory"
    assert cfg["extractor"]["skip"] == "abort:100"
    assert "date-after" not in cfg["extractor"], (
        "force_full_scan must NOT set date-after — that's the whole point of backfill"
    )


@pytest.mark.asyncio
async def test_build_config_normal_subscription_unchanged(mock_site_config_service, mock_config_path):
    """Default subscription path keeps abort:10 + date-after."""
    from plugins.builtin.gallery_dl.source import _build_gallery_dl_config

    await _build_gallery_dl_config(
        credentials={},
        config_id=None,
        job_context="subscription",
        last_completed_at=datetime(2026, 5, 1, 0, 0, 0, tzinfo=UTC),
    )

    cfg = json.loads(mock_config_path.read_text())

    assert cfg["extractor"]["skip"] == "abort:10"
    assert "date-after" in cfg["extractor"]
