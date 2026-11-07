"""Process-wide logging configuration shared by the api and the worker (ADR 0031)."""

import logging
import os
from datetime import datetime

from core.log_redaction import install_log_redaction

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

# SAQ logs Enqueuing/Processing/Finished for every job execution, including the
# admission redeliveries that run every 5 s per waiting download: ~520k lines and
# 167 MB/day measured 2026-11-07. Job executions are traced by our own hooks.
SAQ_LOG_LEVEL = logging.WARNING


class IsoFormatter(logging.Formatter):
    """Local time with milliseconds and UTC offset: 2026-11-07T01:34:55.455+08:00."""

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        return datetime.fromtimestamp(record.created).astimezone().isoformat(timespec="milliseconds")


def configure_logging() -> None:
    """Configure the root logger once per process. Idempotent."""
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO").upper(), format=LOG_FORMAT)
    for handler in logging.getLogger().handlers:
        handler.setFormatter(IsoFormatter(LOG_FORMAT))
    logging.getLogger("saq").setLevel(SAQ_LOG_LEVEL)
    install_log_redaction()
