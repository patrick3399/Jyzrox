"""Shared logging setup (ADR 0031)."""

import logging
import re
from pathlib import Path

import pytest

from core.log_redaction import RedactingFilter
from core.logging_setup import LOG_FORMAT, IsoFormatter, configure_logging


@pytest.fixture
def bare_root():
    root = logging.getLogger()
    saq = logging.getLogger("saq")
    saved_handlers, saved_level, saved_saq = root.handlers[:], root.level, saq.level
    root.handlers = []
    try:
        yield root
    finally:
        root.handlers = saved_handlers
        root.setLevel(saved_level)
        saq.setLevel(saved_saq)


def test_iso_formatter_includes_milliseconds_and_utc_offset():
    record = logging.LogRecord("worker", logging.INFO, __file__, 1, "hello", None, None)
    line = IsoFormatter(LOG_FORMAT).format(record)
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}[+-]\d\d:\d\d \[INFO\] worker: hello", line)


def test_configure_logging_silences_saq_job_lifecycle_info(bare_root):
    configure_logging()
    saq = logging.getLogger("saq")
    assert not saq.isEnabledFor(logging.INFO)
    assert saq.isEnabledFor(logging.WARNING)


def test_configure_logging_formats_and_redacts_every_root_handler(bare_root):
    configure_logging()
    assert bare_root.handlers
    for handler in bare_root.handlers:
        assert isinstance(handler.formatter, IsoFormatter)
        assert any(isinstance(f, RedactingFilter) for f in handler.filters)


def test_api_lifespan_does_not_reattach_uvicorn_access_logger():
    """uvicorn's protocol re-enables access logging when uvicorn.access has any handler,
    so attaching the in-app log handler to it would undo `--no-access-log`."""
    source = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
    assert '"uvicorn.access"' not in source
