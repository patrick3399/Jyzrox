"""Keeps credentials out of worker logs.

SAQ logs ``repr(queue)`` at startup, and redis-py's connection repr carries
``password=<value>``, so the Redis password used to land in ``docker compose
logs worker`` in cleartext on every boot. SAQ gives no hook to change that
line, so the secret is scrubbed on the way out instead.

The filter sits on the *handlers*, not on a logger: a logger-level filter only
sees records logged directly to that logger and would miss ``saq`` and every
other child logger.
"""

import logging
import re
import traceback

_MASK = "***"

# ``password=...`` as redis-py's repr and many client libraries render it.
_KEYWORD_SECRET = re.compile(r"(?i)\b(password|passwd)=([^,)\s&;]+)")
# ``scheme://user:secret@host`` — the user part may be empty (``redis://:secret@host``).
_URL_USERINFO_SECRET = re.compile(r"(\b[a-z][a-z0-9+.\-]*://[^:/@\s]*:)([^@\s/]+)(@)", re.IGNORECASE)


def redact_secrets(text: str) -> str:
    text = _KEYWORD_SECRET.sub(rf"\1={_MASK}", text)
    return _URL_USERINFO_SECRET.sub(rf"\1{_MASK}\3", text)


class RedactingFilter(logging.Filter):
    """Masks secrets in a record's message and exception text. Never drops a record."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            # A malformed format string is the logger's problem to report, not ours to hide.
            return True

        redacted = redact_secrets(message)
        if redacted != message:
            record.msg = redacted
            record.args = None

        if record.exc_info and not record.exc_text:
            # Pre-fill what Formatter would compute so the traceback is masked too.
            trace = "".join(traceback.format_exception(*record.exc_info)).rstrip("\n")
            record.exc_text = redact_secrets(trace)
        elif record.exc_text:
            record.exc_text = redact_secrets(record.exc_text)
        return True


def install_log_redaction(logger: logging.Logger | None = None) -> None:
    """Attach the redacting filter to every handler currently on ``logger`` (default: root).

    Idempotent. Handlers added afterwards are not covered, so call this after
    ``logging.basicConfig``.
    """
    target = logger if logger is not None else logging.getLogger()
    for handler in target.handlers:
        if not any(isinstance(f, RedactingFilter) for f in handler.filters):
            handler.addFilter(RedactingFilter())
