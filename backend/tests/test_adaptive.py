"""Tests for core.adaptive — v3.0 credential-warning-only adaptive engine."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_eval_response(state_dict: dict) -> bytes:
    return json.dumps(state_dict).encode()


def _default_state_dict(**overrides) -> dict:
    base = {
        "credential_warning": False,
        "last_signal": None,
        "last_signal_at": None,
    }
    base.update(overrides)
    return base


def _mock_pipeline():
    pipe = MagicMock()
    pipe.delete = MagicMock()
    pipe.srem = MagicMock()
    pipe.set = MagicMock()
    pipe.execute = AsyncMock(return_value=[])
    return pipe


@pytest.fixture
def mock_redis():
    r = AsyncMock()
    r.eval = AsyncMock()
    r.get = AsyncMock(return_value=None)
    r.sadd = AsyncMock(return_value=1)
    r.spop = AsyncMock(return_value=None)
    r.srem = AsyncMock(return_value=1)
    r.set = AsyncMock()
    pipe = _mock_pipeline()
    r.pipeline = MagicMock(return_value=pipe)
    r._pipe = pipe
    return r


# ── AdaptiveSignal v3 ──


def test_adaptive_signal_v3_only_credential_signals():
    from core.adaptive import AdaptiveSignal

    assert AdaptiveSignal.HTTP_403
    assert AdaptiveSignal.HTML_RESPONSE
    for removed in ("HTTP_429", "HTTP_503", "TIMEOUT", "CONNECTION_ERROR", "SUCCESS", "EMPTY_FILE"):
        assert not hasattr(AdaptiveSignal, removed)


def test_adaptive_signal_is_str_enum():
    from core.adaptive import AdaptiveSignal

    assert isinstance(AdaptiveSignal.HTTP_403, str)
    assert AdaptiveSignal.HTTP_403 == "http_403"
    assert AdaptiveSignal.HTML_RESPONSE == "html_response"


# ── AdaptiveState v3 ──


def test_adaptive_state_v3_has_three_fields():
    from core.adaptive import AdaptiveState

    s = AdaptiveState()
    assert s.credential_warning is False
    assert s.last_signal is None
    assert s.last_signal_at is None
    assert not hasattr(s, "sleep_multiplier")
    assert not hasattr(s, "http_timeout_add")
    assert not hasattr(s, "consecutive_success")


def test_adaptive_state_from_dict():
    from core.adaptive import AdaptiveState

    s = AdaptiveState.from_dict({"credential_warning": True, "last_signal": "http_403"})
    assert s.credential_warning is True
    assert s.last_signal == "http_403"


def test_adaptive_state_from_dict_handles_bad_input():
    from core.adaptive import AdaptiveState

    s = AdaptiveState.from_dict({})
    assert s.credential_warning is False


# ── _validate_download_content (still in source.py, test here for convenience) ──


def test_validate_download_content_returns_empty_for_zero_byte_file(tmp_path):
    from plugins.builtin.gallery_dl.source import _validate_download_content

    f = tmp_path / "empty.jpg"
    f.write_bytes(b"")
    assert _validate_download_content(f) == "empty"


def test_validate_download_content_returns_html_for_small_html_file(tmp_path):
    from plugins.builtin.gallery_dl.source import _validate_download_content

    f = tmp_path / "bad.jpg"
    f.write_bytes(b"<!DOCTYPE html><html><head><title>Access Denied</title></head></html>")
    assert _validate_download_content(f) == "html"


def test_validate_download_content_returns_none_for_valid_binary_file(tmp_path):
    from plugins.builtin.gallery_dl.source import _validate_download_content

    f = tmp_path / "image.jpg"
    f.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * (200 * 1024))
    assert _validate_download_content(f) is None


def test_validate_download_content_returns_none_for_missing_file():
    from plugins.builtin.gallery_dl.source import _validate_download_content

    assert _validate_download_content(Path("/nonexistent/file.jpg")) is None


# ── AdaptiveEngine.record_signal ──


@pytest.mark.asyncio
async def test_record_403_sets_credential_warning(mock_redis):
    from core.adaptive import AdaptiveEngine, AdaptiveSignal

    state_after = _default_state_dict(credential_warning=True, last_signal="http_403")
    mock_redis.eval = AsyncMock(return_value=_make_eval_response(state_after))
    with patch("core.redis_client.get_redis", return_value=mock_redis):
        engine = AdaptiveEngine()
        state = await engine.record_signal("ehentai", AdaptiveSignal.HTTP_403)
    assert state.credential_warning is True
    assert state.last_signal == "http_403"
    mock_redis.eval.assert_called_once()


@pytest.mark.asyncio
async def test_record_html_response_sets_credential_warning(mock_redis):
    from core.adaptive import AdaptiveEngine, AdaptiveSignal

    state_after = _default_state_dict(credential_warning=True, last_signal="html_response")
    mock_redis.eval = AsyncMock(return_value=_make_eval_response(state_after))
    with patch("core.redis_client.get_redis", return_value=mock_redis):
        engine = AdaptiveEngine()
        state = await engine.record_signal("ehentai", AdaptiveSignal.HTML_RESPONSE)
    assert state.credential_warning is True


@pytest.mark.asyncio
async def test_record_signal_no_count_param(mock_redis):
    """v3: record_signal() no longer accepts count parameter."""
    import inspect

    from core.adaptive import AdaptiveEngine

    sig = inspect.signature(AdaptiveEngine.record_signal)
    params = list(sig.parameters.keys())
    assert "count" not in params


# ── AdaptiveEngine.get_state ──


@pytest.mark.asyncio
async def test_get_state_returns_default_when_no_redis_key(mock_redis):
    from core.adaptive import AdaptiveEngine, AdaptiveState

    mock_redis.get = AsyncMock(return_value=None)
    with patch("core.redis_client.get_redis", return_value=mock_redis):
        engine = AdaptiveEngine()
        state = await engine.get_state("unknown_source")
    assert isinstance(state, AdaptiveState)
    assert state.credential_warning is False


@pytest.mark.asyncio
async def test_get_state_returns_parsed_state_from_redis(mock_redis):
    from core.adaptive import AdaptiveEngine

    stored = _default_state_dict(credential_warning=True, last_signal="http_403")
    mock_redis.get = AsyncMock(return_value=json.dumps(stored).encode())
    with patch("core.redis_client.get_redis", return_value=mock_redis):
        engine = AdaptiveEngine()
        state = await engine.get_state("ehentai")
    assert state.credential_warning is True


@pytest.mark.asyncio
async def test_get_state_falls_back_to_db_when_redis_empty(mock_redis):
    from core.adaptive import AdaptiveEngine

    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.set = AsyncMock()
    mock_row = MagicMock()
    mock_row.adaptive = {"credential_warning": True}
    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=mock_row)
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    with (
        patch("core.redis_client.get_redis", return_value=mock_redis),
        patch("core.database.AsyncSessionLocal", return_value=mock_ctx),
    ):
        engine = AdaptiveEngine()
        state = await engine.get_state("ehentai")
    assert state.credential_warning is True
    mock_redis.set.assert_called_once()


# ── AdaptiveEngine.reset ──


@pytest.mark.asyncio
async def test_reset_clears_state_for_source(mock_redis):
    from core.adaptive import AdaptiveEngine

    pipe = _mock_pipeline()
    mock_redis.pipeline = MagicMock(return_value=pipe)
    with patch("core.redis_client.get_redis", return_value=mock_redis):
        engine = AdaptiveEngine()
        await engine.reset("ehentai")
    pipe.delete.assert_called_once_with("adaptive:ehentai")
    pipe.srem.assert_called_once_with("adaptive:dirty", "ehentai")


# ── AdaptiveEngine.persist_dirty ──


@pytest.mark.asyncio
async def test_persist_dirty_writes_db_upsert(mock_redis):
    from core.adaptive import AdaptiveEngine

    mock_redis.spop = AsyncMock(return_value=[b"ehentai"])
    stored = json.dumps(_default_state_dict(credential_warning=True)).encode()
    mock_redis.get = AsyncMock(return_value=stored)
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    with (
        patch("core.redis_client.get_redis", return_value=mock_redis),
        patch("core.database.AsyncSessionLocal", return_value=mock_ctx),
    ):
        engine = AdaptiveEngine()
        count = await engine.persist_dirty()
    assert count == 1


@pytest.mark.asyncio
async def test_persist_dirty_returns_zero_when_empty(mock_redis):
    from core.adaptive import AdaptiveEngine

    mock_redis.spop = AsyncMock(return_value=[])
    with patch("core.redis_client.get_redis", return_value=mock_redis):
        engine = AdaptiveEngine()
        count = await engine.persist_dirty()
    assert count == 0


# ── AdaptiveEngine.load_all_from_db ──


@pytest.mark.asyncio
async def test_load_all_from_db_pipeline_set(mock_redis):
    from core.adaptive import AdaptiveEngine

    row1 = MagicMock()
    row1.source_id = "ehentai"
    row1.adaptive = {"credential_warning": True}
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [row1]
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    pipe = _mock_pipeline()
    mock_redis.pipeline = MagicMock(return_value=pipe)
    with (
        patch("core.redis_client.get_redis", return_value=mock_redis),
        patch("core.database.AsyncSessionLocal", return_value=mock_ctx),
    ):
        engine = AdaptiveEngine()
        count = await engine.load_all_from_db()
    assert count == 1
    assert pipe.set.call_count == 1


@pytest.mark.asyncio
async def test_load_all_from_db_returns_zero_when_no_rows(mock_redis):
    from core.adaptive import AdaptiveEngine

    mock_scalars = MagicMock()
    mock_scalars.all.return_value = []
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    with (
        patch("core.redis_client.get_redis", return_value=mock_redis),
        patch("core.database.AsyncSessionLocal", return_value=mock_ctx),
    ):
        engine = AdaptiveEngine()
        count = await engine.load_all_from_db()
    assert count == 0
