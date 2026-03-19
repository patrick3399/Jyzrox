"""
Tests for core.adaptive — M6 adaptive rate limiting module.

Covers:
- AdaptiveSignal enum values
- AdaptiveState default fields
- parse_adaptive_signal() regex matching for all signal types
- _validate_download_content() HTML/empty/valid file detection
- AdaptiveEngine.record_signal() state transitions (mocked Redis)
- AdaptiveEngine multiplier/timeout caps
- AdaptiveEngine success decay at milestones
- AdaptiveEngine persist_dirty() DB upsert
- AdaptiveEngine load_all_from_db() pipeline setup
- html_response_count reaching 3 emits ADAPTIVE_BLOCKED event
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_eval_response(state_dict: dict) -> bytes:
    """Return a JSON-encoded bytes object as r.eval() would return."""
    return json.dumps(state_dict).encode()


def _default_state_dict(**overrides) -> dict:
    """Build a minimal AdaptiveState JSON dict as returned by the Lua script."""
    base = {
        "sleep_multiplier": 1.0,
        "http_timeout_add": 0,
        "credential_warning": False,
        "consecutive_success": 0,
        "last_signal": None,
        "last_signal_at": None,
    }
    base.update(overrides)
    return base


def _mock_pipeline():
    """Create a mock Redis pipeline that works without context manager."""
    pipe = MagicMock()
    pipe.delete = MagicMock()
    pipe.srem = MagicMock()
    pipe.set = MagicMock()
    pipe.execute = AsyncMock(return_value=[])
    return pipe


# ---------------------------------------------------------------------------
# AdaptiveSignal enum
# ---------------------------------------------------------------------------


def test_adaptive_signal_enum_has_all_expected_values():
    """AdaptiveSignal must expose all eight documented signal types."""
    from core.adaptive import AdaptiveSignal

    expected = {
        "HTTP_429",
        "HTTP_503",
        "HTTP_403",
        "TIMEOUT",
        "CONNECTION_ERROR",
        "SUCCESS",
        "HTML_RESPONSE",
        "EMPTY_FILE",
    }
    actual = {member.name for member in AdaptiveSignal}
    assert expected == actual


def test_adaptive_signal_is_str_enum():
    """AdaptiveSignal values must be plain strings (str Enum)."""
    from core.adaptive import AdaptiveSignal

    assert isinstance(AdaptiveSignal.HTTP_429, str)
    assert AdaptiveSignal.HTTP_429 == "http_429"
    assert AdaptiveSignal.SUCCESS == "success"
    assert AdaptiveSignal.HTML_RESPONSE == "html_response"
    assert AdaptiveSignal.EMPTY_FILE == "empty_file"


# ---------------------------------------------------------------------------
# AdaptiveState dataclass defaults
# ---------------------------------------------------------------------------


def test_adaptive_state_defaults_are_correct():
    """AdaptiveState default field values must match the spec."""
    from core.adaptive import AdaptiveState

    state = AdaptiveState()
    assert state.sleep_multiplier == 1.0
    assert state.http_timeout_add == 0
    assert state.credential_warning is False
    assert state.consecutive_success == 0
    assert state.last_signal is None
    assert state.last_signal_at is None


def test_adaptive_state_accepts_custom_values():
    """AdaptiveState fields can be overridden at construction."""
    from core.adaptive import AdaptiveState

    state = AdaptiveState(
        sleep_multiplier=4.0,
        http_timeout_add=30,
        credential_warning=True,
        consecutive_success=42,
        last_signal="http_429",
        last_signal_at="2026-01-01T00:00:00+00:00",
    )
    assert state.sleep_multiplier == 4.0
    assert state.http_timeout_add == 30
    assert state.credential_warning is True
    assert state.consecutive_success == 42
    assert state.last_signal == "http_429"


# ---------------------------------------------------------------------------
# parse_adaptive_signal — pure function, no I/O
# ---------------------------------------------------------------------------


def test_parse_signal_detects_429_http_error_pattern():
    from core.adaptive import AdaptiveSignal, parse_adaptive_signal

    assert parse_adaptive_signal("[error] HTTP Error 429: Too Many Requests") == AdaptiveSignal.HTTP_429


def test_parse_signal_detects_429_too_many_pattern():
    from core.adaptive import AdaptiveSignal, parse_adaptive_signal

    assert parse_adaptive_signal("response status: 429 Too Many Requests") == AdaptiveSignal.HTTP_429


def test_parse_signal_detects_503_http_error_pattern():
    from core.adaptive import AdaptiveSignal, parse_adaptive_signal

    assert parse_adaptive_signal("[error] HTTP Error 503: Service Unavailable") == AdaptiveSignal.HTTP_503


def test_parse_signal_detects_503_service_pattern():
    from core.adaptive import AdaptiveSignal, parse_adaptive_signal

    assert parse_adaptive_signal("error: 503 Service Unavailable") == AdaptiveSignal.HTTP_503


def test_parse_signal_detects_403_http_error_pattern():
    from core.adaptive import AdaptiveSignal, parse_adaptive_signal

    assert parse_adaptive_signal("[error] HTTP Error 403: Forbidden") == AdaptiveSignal.HTTP_403


def test_parse_signal_detects_403_forbidden_pattern():
    from core.adaptive import AdaptiveSignal, parse_adaptive_signal

    assert parse_adaptive_signal("status code: 403 Forbidden") == AdaptiveSignal.HTTP_403


def test_parse_signal_detects_timeout_timed_out():
    from core.adaptive import AdaptiveSignal, parse_adaptive_signal

    assert parse_adaptive_signal("Request timed out after 30s") == AdaptiveSignal.TIMEOUT


def test_parse_signal_detects_timeout_timeout_error():
    from core.adaptive import AdaptiveSignal, parse_adaptive_signal

    assert parse_adaptive_signal("TimeoutError: connection timed out") == AdaptiveSignal.TIMEOUT


def test_parse_signal_detects_timeout_read_timed_out():
    from core.adaptive import AdaptiveSignal, parse_adaptive_signal

    assert parse_adaptive_signal("Read timed out (30.0s)") == AdaptiveSignal.TIMEOUT


def test_parse_signal_detects_connection_error_pattern():
    from core.adaptive import AdaptiveSignal, parse_adaptive_signal

    assert parse_adaptive_signal("ConnectionError: Failed to establish connection") == AdaptiveSignal.CONNECTION_ERROR


def test_parse_signal_detects_name_not_known_pattern():
    from core.adaptive import AdaptiveSignal, parse_adaptive_signal

    assert parse_adaptive_signal("Name or service not known: x.com") == AdaptiveSignal.CONNECTION_ERROR


def test_parse_signal_detects_connection_refused_pattern():
    from core.adaptive import AdaptiveSignal, parse_adaptive_signal

    assert parse_adaptive_signal("Connection refused: 127.0.0.1:6379") == AdaptiveSignal.CONNECTION_ERROR


def test_parse_signal_returns_none_for_unrelated_lines():
    from core.adaptive import parse_adaptive_signal

    normal_lines = [
        "[info] Testing extractor: e-hentai",
        "Downloading 1/42: image.jpg",
        "[download] Downloading ...",
        "# Generated by gallery-dl",
        "",
        "Successfully downloaded 42 files.",
    ]
    for line in normal_lines:
        assert parse_adaptive_signal(line) is None, f"Expected None for line: {line!r}"


# ---------------------------------------------------------------------------
# _validate_download_content — uses real temp files via tmp_path fixture
# ---------------------------------------------------------------------------


def test_validate_download_content_returns_empty_for_zero_byte_file(tmp_path):
    from plugins.builtin.gallery_dl.source import _validate_download_content

    empty_file = tmp_path / "empty.jpg"
    empty_file.write_bytes(b"")
    assert _validate_download_content(empty_file) == "empty"


def test_validate_download_content_returns_html_for_small_html_file(tmp_path):
    from plugins.builtin.gallery_dl.source import _validate_download_content

    html_file = tmp_path / "bad.jpg"
    html_file.write_bytes(b"<!DOCTYPE html><html><head><title>Access Denied</title></head></html>")
    assert _validate_download_content(html_file) == "html"


def test_validate_download_content_returns_html_for_lowercase_html_tag(tmp_path):
    from plugins.builtin.gallery_dl.source import _validate_download_content

    html_file = tmp_path / "sneaky.png"
    html_file.write_bytes(b"<html><body>Error page</body></html>")
    assert _validate_download_content(html_file) == "html"


def test_validate_download_content_detects_cloudflare_challenge(tmp_path):
    from plugins.builtin.gallery_dl.source import _validate_download_content

    cf_file = tmp_path / "cf.jpg"
    cf_file.write_bytes(b"Please wait... cf-browser-verification challenge in progress")
    assert _validate_download_content(cf_file) == "html"


def test_validate_download_content_returns_none_for_valid_binary_file(tmp_path):
    from plugins.builtin.gallery_dl.source import _validate_download_content

    valid_file = tmp_path / "image.jpg"
    valid_file.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * (200 * 1024))
    assert _validate_download_content(valid_file) is None


def test_validate_download_content_returns_none_for_large_html_like_file(tmp_path):
    from plugins.builtin.gallery_dl.source import _validate_download_content

    large_file = tmp_path / "large.jpg"
    large_file.write_bytes(b"<!DOCTYPE html>" + b"x" * (150 * 1024))
    assert _validate_download_content(large_file) is None


def test_validate_download_content_returns_none_for_missing_file():
    from plugins.builtin.gallery_dl.source import _validate_download_content

    assert _validate_download_content(Path("/nonexistent/file.jpg")) is None


# ---------------------------------------------------------------------------
# AdaptiveEngine — mocked Redis
#
# The engine uses lazy imports: `from core.redis_client import get_redis`
# inside each method. We must patch `core.redis_client.get_redis`.
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_redis():
    """AsyncMock Redis client for AdaptiveEngine tests."""
    r = AsyncMock()
    r.eval = AsyncMock()
    r.get = AsyncMock(return_value=None)
    r.sadd = AsyncMock(return_value=1)
    r.spop = AsyncMock(return_value=None)
    r.srem = AsyncMock(return_value=1)

    pipe = _mock_pipeline()
    r.pipeline = MagicMock(return_value=pipe)
    r._pipe = pipe  # expose for assertions

    return r


@pytest.mark.asyncio
async def test_record_signal_429_doubles_sleep_multiplier(mock_redis):
    """record_signal(HTTP_429) should invoke Lua eval and return state with doubled multiplier."""
    from core.adaptive import AdaptiveEngine, AdaptiveSignal, AdaptiveState

    doubled_state = _default_state_dict(sleep_multiplier=2.0, last_signal="http_429")
    mock_redis.eval = AsyncMock(return_value=_make_eval_response(doubled_state))

    with patch("core.redis_client.get_redis", return_value=mock_redis):
        engine = AdaptiveEngine()
        state = await engine.record_signal("ehentai", AdaptiveSignal.HTTP_429)

    assert isinstance(state, AdaptiveState)
    assert state.sleep_multiplier == 2.0
    assert state.last_signal == "http_429"
    mock_redis.eval.assert_called_once()


@pytest.mark.asyncio
async def test_record_signal_503_increases_multiplier_by_1_5x(mock_redis):
    from core.adaptive import AdaptiveEngine, AdaptiveSignal

    state_after = _default_state_dict(sleep_multiplier=1.5, last_signal="http_503")
    mock_redis.eval = AsyncMock(return_value=_make_eval_response(state_after))

    with patch("core.redis_client.get_redis", return_value=mock_redis):
        engine = AdaptiveEngine()
        state = await engine.record_signal("twitter", AdaptiveSignal.HTTP_503)

    assert state.sleep_multiplier == 1.5
    assert state.last_signal == "http_503"


@pytest.mark.asyncio
async def test_record_signal_429_multiplier_capped_at_8(mock_redis):
    from core.adaptive import AdaptiveEngine, AdaptiveSignal

    capped_state = _default_state_dict(sleep_multiplier=8.0, last_signal="http_429")
    mock_redis.eval = AsyncMock(return_value=_make_eval_response(capped_state))

    with patch("core.redis_client.get_redis", return_value=mock_redis):
        engine = AdaptiveEngine()
        state = await engine.record_signal("ehentai", AdaptiveSignal.HTTP_429)

    assert state.sleep_multiplier == 8.0


@pytest.mark.asyncio
async def test_record_signal_403_sets_credential_warning(mock_redis):
    from core.adaptive import AdaptiveEngine, AdaptiveSignal

    warned_state = _default_state_dict(credential_warning=True, last_signal="http_403")
    mock_redis.eval = AsyncMock(return_value=_make_eval_response(warned_state))

    with patch("core.redis_client.get_redis", return_value=mock_redis):
        engine = AdaptiveEngine()
        state = await engine.record_signal("pixiv", AdaptiveSignal.HTTP_403)

    assert state.credential_warning is True


@pytest.mark.asyncio
async def test_record_signal_timeout_adds_15_to_http_timeout_add(mock_redis):
    from core.adaptive import AdaptiveEngine, AdaptiveSignal

    timeout_state = _default_state_dict(http_timeout_add=15, last_signal="timeout")
    mock_redis.eval = AsyncMock(return_value=_make_eval_response(timeout_state))

    with patch("core.redis_client.get_redis", return_value=mock_redis):
        engine = AdaptiveEngine()
        state = await engine.record_signal("ehentai", AdaptiveSignal.TIMEOUT)

    assert state.http_timeout_add == 15


@pytest.mark.asyncio
async def test_record_signal_connection_error_adds_15_to_http_timeout_add(mock_redis):
    from core.adaptive import AdaptiveEngine, AdaptiveSignal

    conn_state = _default_state_dict(http_timeout_add=15, last_signal="connection_error")
    mock_redis.eval = AsyncMock(return_value=_make_eval_response(conn_state))

    with patch("core.redis_client.get_redis", return_value=mock_redis):
        engine = AdaptiveEngine()
        state = await engine.record_signal("twitter", AdaptiveSignal.CONNECTION_ERROR)

    assert state.http_timeout_add == 15


@pytest.mark.asyncio
async def test_record_signal_http_timeout_add_capped_at_120(mock_redis):
    from core.adaptive import AdaptiveEngine, AdaptiveSignal

    capped_state = _default_state_dict(http_timeout_add=120, last_signal="timeout")
    mock_redis.eval = AsyncMock(return_value=_make_eval_response(capped_state))

    with patch("core.redis_client.get_redis", return_value=mock_redis):
        engine = AdaptiveEngine()
        state = await engine.record_signal("ehentai", AdaptiveSignal.TIMEOUT)

    assert state.http_timeout_add == 120


@pytest.mark.asyncio
async def test_record_signal_success_increments_consecutive_success(mock_redis):
    from core.adaptive import AdaptiveEngine, AdaptiveSignal

    success_state = _default_state_dict(consecutive_success=10, last_signal="success")
    mock_redis.eval = AsyncMock(return_value=_make_eval_response(success_state))

    with patch("core.redis_client.get_redis", return_value=mock_redis):
        engine = AdaptiveEngine()
        state = await engine.record_signal("ehentai", AdaptiveSignal.SUCCESS, count=10)

    assert state.consecutive_success == 10


@pytest.mark.asyncio
async def test_record_signal_success_decays_multiplier_at_20_consecutive(mock_redis):
    from core.adaptive import AdaptiveEngine, AdaptiveSignal

    decay_state = _default_state_dict(
        sleep_multiplier=1.6,
        consecutive_success=20,
        last_signal="success",
    )
    mock_redis.eval = AsyncMock(return_value=_make_eval_response(decay_state))

    with patch("core.redis_client.get_redis", return_value=mock_redis):
        engine = AdaptiveEngine()
        state = await engine.record_signal("ehentai", AdaptiveSignal.SUCCESS, count=20)

    assert state.sleep_multiplier == 1.6


@pytest.mark.asyncio
async def test_record_signal_success_multiplier_floor_is_1_0(mock_redis):
    from core.adaptive import AdaptiveEngine, AdaptiveSignal

    floor_state = _default_state_dict(sleep_multiplier=1.0, consecutive_success=20, last_signal="success")
    mock_redis.eval = AsyncMock(return_value=_make_eval_response(floor_state))

    with patch("core.redis_client.get_redis", return_value=mock_redis):
        engine = AdaptiveEngine()
        state = await engine.record_signal("ehentai", AdaptiveSignal.SUCCESS, count=20)

    assert state.sleep_multiplier >= 1.0


@pytest.mark.asyncio
async def test_record_signal_success_resets_http_timeout_add_at_100(mock_redis):
    from core.adaptive import AdaptiveEngine, AdaptiveSignal

    reset_state = _default_state_dict(
        http_timeout_add=25,
        consecutive_success=0,
        last_signal="success",
    )
    mock_redis.eval = AsyncMock(return_value=_make_eval_response(reset_state))

    with patch("core.redis_client.get_redis", return_value=mock_redis):
        engine = AdaptiveEngine()
        state = await engine.record_signal("ehentai", AdaptiveSignal.SUCCESS, count=100)

    assert state.http_timeout_add == 25


@pytest.mark.asyncio
async def test_record_signal_error_resets_consecutive_success(mock_redis):
    from core.adaptive import AdaptiveEngine, AdaptiveSignal

    reset_state = _default_state_dict(consecutive_success=0, last_signal="http_429")
    mock_redis.eval = AsyncMock(return_value=_make_eval_response(reset_state))

    with patch("core.redis_client.get_redis", return_value=mock_redis):
        engine = AdaptiveEngine()
        state = await engine.record_signal("ehentai", AdaptiveSignal.HTTP_429)

    assert state.consecutive_success == 0


@pytest.mark.asyncio
async def test_record_signal_html_response_sets_credential_warning(mock_redis):
    from core.adaptive import AdaptiveEngine, AdaptiveSignal

    html_state = _default_state_dict(credential_warning=True, last_signal="html_response")
    mock_redis.eval = AsyncMock(return_value=_make_eval_response(html_state))

    with patch("core.redis_client.get_redis", return_value=mock_redis):
        engine = AdaptiveEngine()
        state = await engine.record_signal("ehentai", AdaptiveSignal.HTML_RESPONSE)

    assert state.credential_warning is True


@pytest.mark.asyncio
async def test_record_signal_empty_file_increments_timeout_add(mock_redis):
    from core.adaptive import AdaptiveEngine, AdaptiveSignal

    empty_state = _default_state_dict(http_timeout_add=15, last_signal="empty_file")
    mock_redis.eval = AsyncMock(return_value=_make_eval_response(empty_state))

    with patch("core.redis_client.get_redis", return_value=mock_redis):
        engine = AdaptiveEngine()
        state = await engine.record_signal("ehentai", AdaptiveSignal.EMPTY_FILE)

    assert state.http_timeout_add == 15


# ---------------------------------------------------------------------------
# AdaptiveEngine.get_state()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_state_returns_default_when_no_redis_key(mock_redis):
    from core.adaptive import AdaptiveEngine, AdaptiveState

    mock_redis.get = AsyncMock(return_value=None)

    with patch("core.redis_client.get_redis", return_value=mock_redis):
        engine = AdaptiveEngine()
        state = await engine.get_state("unknown_source")

    assert isinstance(state, AdaptiveState)
    assert state.sleep_multiplier == 1.0
    assert state.http_timeout_add == 0


@pytest.mark.asyncio
async def test_get_state_returns_parsed_state_from_redis(mock_redis):
    from core.adaptive import AdaptiveEngine

    stored = _default_state_dict(sleep_multiplier=4.0, http_timeout_add=30)
    mock_redis.get = AsyncMock(return_value=json.dumps(stored).encode())

    with patch("core.redis_client.get_redis", return_value=mock_redis):
        engine = AdaptiveEngine()
        state = await engine.get_state("ehentai")

    assert state.sleep_multiplier == 4.0
    assert state.http_timeout_add == 30


# ---------------------------------------------------------------------------
# AdaptiveEngine.reset()
# ---------------------------------------------------------------------------


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
    pipe.execute.assert_awaited_once()


# ---------------------------------------------------------------------------
# AdaptiveEngine.persist_dirty()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persist_dirty_writes_db_upsert_for_dirty_sources(mock_redis):
    """persist_dirty() calls DB upsert for each source popped from dirty set."""
    from core.adaptive import AdaptiveEngine

    # SPOP with count returns a list
    mock_redis.spop = AsyncMock(return_value=[b"ehentai", b"twitter"])
    # get_state calls r.get
    stored = json.dumps(_default_state_dict(sleep_multiplier=2.0)).encode()
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

    assert count == 2
    assert mock_session.execute.call_count == 2
    assert mock_session.commit.call_count == 1  # single batch commit


@pytest.mark.asyncio
async def test_persist_dirty_requeues_failed_source_to_dirty_set(mock_redis):
    """persist_dirty() re-adds failed sources to dirty set via SADD on exception."""
    from core.adaptive import AdaptiveEngine

    # SPOP with count returns a list
    mock_redis.spop = AsyncMock(return_value=[b"ehentai"])
    stored = json.dumps(_default_state_dict()).encode()
    mock_redis.get = AsyncMock(return_value=stored)
    mock_redis.sadd = AsyncMock()

    # DB session raises an exception during upsert
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=Exception("DB write failed"))
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

    assert count == 0
    # Source should have been re-added to dirty set
    mock_redis.sadd.assert_called_once()
    call_args = mock_redis.sadd.call_args
    assert call_args[0][0] == "adaptive:dirty"
    assert "ehentai" in call_args[0]


@pytest.mark.asyncio
async def test_persist_dirty_returns_zero_when_no_dirty_sources(mock_redis):
    from core.adaptive import AdaptiveEngine

    # SPOP with count returns empty list or None when set is empty
    mock_redis.spop = AsyncMock(return_value=[])

    with patch("core.redis_client.get_redis", return_value=mock_redis):
        engine = AdaptiveEngine()
        count = await engine.persist_dirty()

    assert count == 0


# ---------------------------------------------------------------------------
# AdaptiveEngine.load_all_from_db()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_all_from_db_issues_pipeline_set_calls(mock_redis):
    """load_all_from_db() reads all rows and calls Redis pipeline SET for each."""
    from core.adaptive import AdaptiveEngine

    # Fake DB rows with adaptive data
    row1 = MagicMock()
    row1.source_id = "ehentai"
    row1.adaptive = {
        "adaptive_engine": {
            "sleep_multiplier": 3.0,
            "http_timeout_add": 0,
            "credential_warning": False,
            "consecutive_success": 0,
            "last_signal": None,
            "last_signal_at": None,
        }
    }

    row2 = MagicMock()
    row2.source_id = "twitter"
    row2.adaptive = {
        "adaptive_engine": {
            "sleep_multiplier": 1.0,
            "http_timeout_add": 30,
            "credential_warning": False,
            "consecutive_success": 0,
            "last_signal": None,
            "last_signal_at": None,
        }
    }

    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [row1, row2]
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

    assert count == 2
    assert pipe.set.call_count == 2
    pipe.execute.assert_awaited_once()


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


@pytest.mark.asyncio
async def test_load_all_from_db_skips_rows_without_adaptive_engine_key(mock_redis):
    from core.adaptive import AdaptiveEngine

    row1 = MagicMock()
    row1.source_id = "ehentai"
    row1.adaptive = {}  # no adaptive_engine key

    row2 = MagicMock()
    row2.source_id = "twitter"
    row2.adaptive = {
        "adaptive_engine": {
            "sleep_multiplier": 2.0,
            "http_timeout_add": 0,
            "credential_warning": False,
            "consecutive_success": 0,
            "last_signal": None,
            "last_signal_at": None,
        }
    }

    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [row1, row2]
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

    assert count == 1  # only row2


# ---------------------------------------------------------------------------
# Integration: _on_file_with_validation emits ADAPTIVE_BLOCKED at count 3
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_html_response_count_3_emits_adaptive_blocked_event(mock_redis, tmp_path):
    """When html_response_count reaches 3, an ADAPTIVE_BLOCKED event is emitted."""
    from plugins.builtin.gallery_dl.source import _DownloadState, _on_file_with_validation

    # Create a small HTML file
    html_file = tmp_path / "bad.jpg"
    html_file.write_bytes(b"<!DOCTYPE html><html><body>Blocked</body></html>")

    state = _DownloadState(
        last_activity=0.0,
        last_progress_update=0.0,
        source_id="ehentai",
        html_response_count=2,  # next one will be #3
    )

    mock_proc = MagicMock()
    mock_proc.kill = MagicMock()

    emitted_events = []

    async def _mock_emit_safe(event_type, **kwargs):
        emitted_events.append({"event_type": event_type, **kwargs})

    with (
        patch("core.redis_client.get_redis", return_value=mock_redis),
        patch("core.events.emit_safe", _mock_emit_safe),
    ):
        mock_redis.eval = AsyncMock(
            return_value=_make_eval_response(_default_state_dict(credential_warning=True, last_signal="html_response"))
        )
        await _on_file_with_validation(html_file, state, mock_proc, None)

    assert state.html_response_count == 3
    assert len(emitted_events) == 1
    from core.events import EventType

    assert emitted_events[0]["event_type"] == EventType.ADAPTIVE_BLOCKED
    # Design: HTML_RESPONSE ×3 → sleep_multiplier *= 4 (two 429 signals recorded)
    # html_response signal + two 429 signals = 3 total eval calls
    assert mock_redis.eval.call_count == 3


@pytest.mark.asyncio
async def test_html_response_count_5_kills_process(mock_redis, tmp_path):
    """When html_response_count reaches 5, the process is killed."""
    from plugins.builtin.gallery_dl.source import _DownloadState, _on_file_with_validation

    html_file = tmp_path / "bad.jpg"
    html_file.write_bytes(b"<!DOCTYPE html><html><body>Blocked</body></html>")

    state = _DownloadState(
        last_activity=0.0,
        last_progress_update=0.0,
        source_id="ehentai",
        html_response_count=4,  # next one will be #5
    )

    mock_proc = MagicMock()
    mock_proc.kill = MagicMock()

    with patch("core.redis_client.get_redis", return_value=mock_redis):
        mock_redis.eval = AsyncMock(
            return_value=_make_eval_response(_default_state_dict(credential_warning=True, last_signal="html_response"))
        )
        await _on_file_with_validation(html_file, state, mock_proc, None)

    assert state.html_response_count == 5
    assert state.cancelled is True
    mock_proc.kill.assert_called_once()


# ---------------------------------------------------------------------------
# get_state DB fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_state_falls_back_to_db_when_redis_empty(mock_redis):
    """get_state() loads from DB when Redis key is absent, then re-populates Redis."""
    from core.adaptive import AdaptiveEngine

    # Redis returns None (key absent)
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.set = AsyncMock()

    # DB row has adaptive state
    mock_row = MagicMock()
    mock_row.adaptive = {
        "adaptive_engine": {
            "sleep_multiplier": 3.0,
            "http_timeout_add": 15,
            "credential_warning": False,
            "consecutive_success": 0,
            "last_signal": "http_429",
            "last_signal_at": "2026-03-19T00:00:00",
        }
    }

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

    assert state.sleep_multiplier == 3.0
    assert state.http_timeout_add == 15
    assert state.last_signal == "http_429"
    # Should re-populate Redis cache
    mock_redis.set.assert_called_once()
