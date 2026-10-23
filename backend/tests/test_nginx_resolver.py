"""Regression: nginx must retry a failed upstream lookup as fast as a good one.

With `server api:8000 resolve`, `valid` paces re-resolution only after a
successful answer. While a recreated container is gone (e.g. during the deploy's
`migrate` step) Docker DNS answers SERVFAIL, and nginx then keeps the dead IP and
retries every `resolver_timeout` -- 30s by default. Measured 2026-10-23 on
nginx 1.30.6: failures logged at :59, :29, :59; /api returned 502 for ~15s after
the new api was healthy. `resolver_timeout 5s` makes it retry every 5s.
"""

import re
from pathlib import Path

import pytest

_TEMPLATE = Path(__file__).resolve().parents[2] / "nginx" / "nginx.conf.template"


def _seconds(value: str) -> int:
    m = re.fullmatch(r"(\d+)(s?)", value)
    assert m, f"unsupported nginx time value: {value}"
    return int(m.group(1))


@pytest.mark.skipif(not _TEMPLATE.exists(), reason="nginx template is outside this checkout")
def test_nginx_failed_upstream_lookup_retries_no_slower_than_valid():
    conf = _TEMPLATE.read_text(encoding="utf-8")
    conf = "\n".join(line.split("#", 1)[0] for line in conf.splitlines())

    resolver = re.search(r"^\s*resolver\s+[^;]*\bvalid=(\w+)", conf, re.M)
    assert resolver, "upstreams use `resolve`, so a resolver with valid= is required"
    timeout = re.search(r"^\s*resolver_timeout\s+(\w+)\s*;", conf, re.M)
    assert timeout, "resolver_timeout unset: a failed lookup is retried only every 30s (nginx default)"
    assert _seconds(timeout.group(1)) <= _seconds(resolver.group(1))
