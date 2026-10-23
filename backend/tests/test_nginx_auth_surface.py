"""Regression: what nginx exposes to unauthenticated clients behind the outer proxy.

Measured 2026-10-23: every external request reaches nginx from the outer reverse
proxy (192.168.10.201), so `limit_req` keyed on `$binary_remote_addr` was one
bucket for the whole internet -- five login attempts a minute for everyone,
which any single client could spend. And `/api/auth/check` accepted HTTP Basic
credentials straight from the internet with no per-client limit.
"""

import re
from pathlib import Path

import pytest

from core.config import Settings

_TEMPLATE = Path(__file__).resolve().parents[2] / "nginx" / "nginx.conf.template"

pytestmark = pytest.mark.skipif(not _TEMPLATE.exists(), reason="nginx template is outside this checkout")


def _conf() -> str:
    conf = _TEMPLATE.read_text(encoding="utf-8")
    return "\n".join(line.split("#", 1)[0] for line in conf.splitlines())


def _location(conf: str, matcher: str) -> str:
    m = re.search(r"location\s+" + matcher + r"\s*\{([^{}]*)\}", conf)
    assert m, f"no location {matcher} block"
    return m.group(1)


def test_nginx_behind_outer_proxy_keys_limits_on_client_address():
    conf = _conf()

    trusted = set(re.findall(r"^\s*set_real_ip_from\s+(\S+)\s*;", conf, re.M))
    backend_trusted = {cidr.strip() for cidr in Settings.model_fields["trusted_proxies"].default.split(",")}
    # Same trust boundary as the backend's get_client_ip(), so nginx limits and
    # backend limits key on the same client.
    assert trusted == backend_trusted
    assert re.search(r"^\s*real_ip_header\s+X-Forwarded-For\s*;", conf, re.M)
    # Without recursion nginx takes the last hop -- the outer proxy itself.
    assert re.search(r"^\s*real_ip_recursive\s+on\s*;", conf, re.M)


def test_nginx_external_auth_check_drops_basic_credentials():
    block = _location(_conf(), r"=\s*/api/auth/check")

    # The PWA login page still calls it with its cookie; only Basic is cut off.
    assert re.search(r'proxy_set_header\s+Authorization\s+""\s*;', block)
    assert "proxy_pass http://api;" in block


@pytest.mark.parametrize("name", ["/_auth", "/_auth_media"])
def test_nginx_basic_auth_subrequest_forwards_client_address(name):
    block = _location(_conf(), r"=\s*" + re.escape(name))

    # /media/* auth_request still carries Basic credentials (OPDS readers); the
    # backend budgets failures per client, which needs the client's address.
    assert re.search(r"proxy_set_header\s+X-Forwarded-For\s+\$proxy_add_x_forwarded_for\s*;", block)
