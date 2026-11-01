"""Regression coverage for credentials leaking into worker logs.

SAQ logs ``repr(queue)`` at startup ("Worker starting: RedisQueue<redis=...>").
redis-py's connection repr includes ``password=<value>``, so every worker boot
wrote the Redis password into ``docker compose logs worker`` in cleartext —
once per SAQ worker, three times per start.
"""

import io
import logging

import pytest

SECRET = "s3cr3t-r3dis-pw"


def _logger_with_redaction(name: str) -> tuple[logging.Logger, io.StringIO]:
    from worker.log_redaction import install_log_redaction

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
    log = logging.getLogger(name)
    log.handlers = [handler]
    log.propagate = False
    log.setLevel(logging.INFO)
    install_log_redaction(log)
    return log, stream


class TestRedactSecrets:
    def test_redis_connection_repr_password_is_masked(self):
        from worker.log_redaction import redact_secrets

        text = f"Connection(password={SECRET},host=redis,port=6379)"

        out = redact_secrets(text)

        assert SECRET not in out
        assert "host=redis,port=6379" in out, "only the secret may be removed, not the diagnostic context"

    def test_password_in_redis_url_is_masked(self):
        from worker.log_redaction import redact_secrets

        out = redact_secrets(f"connecting to redis://:{SECRET}@redis:6379/0")

        assert SECRET not in out
        assert "@redis:6379/0" in out

    def test_password_in_url_with_username_is_masked(self):
        from worker.log_redaction import redact_secrets

        out = redact_secrets(f"postgresql://vault:{SECRET}@postgres:5432/vault")

        assert SECRET not in out
        assert "vault" in out and "@postgres:5432/vault" in out

    def test_text_without_secrets_is_returned_unchanged(self):
        from worker.log_redaction import redact_secrets

        text = "[progressive] imported: 2092948190224101502_1.jpg (page 770)"

        assert redact_secrets(text) == text


class TestRedactingFilterOnRealLogging:
    def test_saq_queue_repr_logged_by_saq_does_not_contain_the_password(self):
        """The exact shape that leaked: logger.info("...: %s", repr(queue))."""
        from saq import Queue

        log, stream = _logger_with_redaction("test_redaction.saq_repr")
        queue = Queue.from_url(f"redis://:{SECRET}@redis:6379", name="interactive")
        assert SECRET in repr(queue), "precondition: the library really does put the password in repr"

        log.info("Worker starting: %s", repr(queue))

        assert SECRET not in stream.getvalue()
        assert "Worker starting: RedisQueue<" in stream.getvalue(), "the line itself must still be logged"

    def test_secret_passed_as_lazy_format_arg_is_masked(self):
        log, stream = _logger_with_redaction("test_redaction.lazy_arg")

        log.warning("cannot connect: %s", f"Connection(password={SECRET},host=redis)")

        assert SECRET not in stream.getvalue()

    def test_secret_inside_exception_text_is_masked(self):
        log, stream = _logger_with_redaction("test_redaction.exc")

        try:
            raise ConnectionError(f"bad auth for redis://:{SECRET}@redis:6379")
        except ConnectionError:
            log.exception("redis failed")

        assert SECRET not in stream.getvalue()

    def test_child_logger_records_are_masked_by_a_handler_level_filter(self):
        """A filter on a *logger* skips child loggers' records; it must sit on the handler."""
        from worker.log_redaction import install_log_redaction

        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        root = logging.getLogger("test_redaction.root")
        root.handlers = [handler]
        root.propagate = False
        root.setLevel(logging.INFO)
        install_log_redaction(root)

        logging.getLogger("test_redaction.root.child.deeper").info("pw=Connection(password=%s)", SECRET)

        assert SECRET not in stream.getvalue()
        assert stream.getvalue().strip(), "the child record must still be emitted"

    @pytest.mark.parametrize("level", [logging.DEBUG, logging.INFO, logging.ERROR])
    def test_filter_never_drops_a_record(self, level):
        log, stream = _logger_with_redaction(f"test_redaction.keep.{level}")
        log.setLevel(logging.DEBUG)

        log.log(level, "ordinary message")

        assert "ordinary message" in stream.getvalue()
