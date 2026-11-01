"""services.browser_http: an httpx transport that connects through curl_cffi as Chrome.

Every request here goes to a local server; the TLS / HTTP/2 fingerprint itself
is checked once by hand against a public echo service (see the plan).
"""

import asyncio
import gzip
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest
from curl_cffi import CurlECode, CurlError

from core.client_identity import BROWSER_TARGET, BROWSER_USER_AGENT, browser_base_headers, browser_headers
from services.browser_http import ImpersonatingTransport, TLSHandshakeError, _to_httpx_error, browser_client

# curl adds these on plain-http requests (an h2c upgrade offer); over https they do not exist.
_CURL_PLAIN_HTTP_ONLY = {"host", "connection", "upgrade", "http2-settings"}


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False

    def handle_error(self, request, client_address):
        pass  # clients that time out or cancel on purpose break the pipe


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _reply(self, status, body=b"", headers=()):
        self.send_response(status)
        for name, value in headers:
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _record(self, body=b""):
        self.server.seen.append(
            {"method": self.command, "path": self.path, "headers": list(self.headers.items()), "body": body}
        )

    def do_GET(self):
        self._record()
        if self.path == "/redirect":
            return self._reply(302, headers=[("Location", "/final"), ("Set-Cookie", "sk=abc; Path=/")])
        if self.path == "/set-cookie":
            return self._reply(200, b"ok", [("Set-Cookie", "session=1; Path=/")])
        if self.path == "/gzip":
            return self._reply(200, gzip.compress(b"decoded body"), [("Content-Encoding", "gzip")])
        if self.path == "/stall":
            time.sleep(3)
        return self._reply(200, b"ok", [("X-Multi", "1"), ("X-Multi", "2")])

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self._record(body)
        return self._reply(200, b"ok")

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    srv = _Server(("127.0.0.1", 0), _Handler)
    srv.seen = []
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def _url(server, path="/"):
    return f"http://127.0.0.1:{server.server_port}{path}"


def _names(record):
    return [name.lower() for name, _ in record["headers"] if name.lower() not in _CURL_PLAIN_HTTP_ONLY]


def _values(record, name):
    return [value for key, value in record["headers"] if key.lower() == name]


# ---------------------------------------------------------------------------
# Header order and forwarding
# ---------------------------------------------------------------------------


async def test_navigation_headers_go_out_in_chrome_navigation_order(server):
    async with browser_client(timeout=5) as client:
        await client.get(
            _url(server), headers=browser_headers("document", site="none", referer="https://e-hentai.org/")
        )

    # Priority is absent because curl, like Chrome, sends it only over HTTP/2.
    assert _names(server.seen[0]) == [
        "sec-ch-ua",
        "sec-ch-ua-mobile",
        "sec-ch-ua-platform",
        "upgrade-insecure-requests",
        "user-agent",
        "accept",
        "sec-fetch-site",
        "sec-fetch-mode",
        "sec-fetch-user",
        "sec-fetch-dest",
        "referer",
        "accept-encoding",
        "accept-language",
    ]


async def test_subresource_headers_go_out_in_chrome_subresource_order(server):
    async with browser_client(timeout=5, cookies={"ipb_member_id": "1"}) as client:
        await client.get(
            _url(server), headers=browser_headers("image", site="cross-site", referer="https://e-hentai.org/")
        )

    assert _names(server.seen[0]) == [
        "sec-ch-ua-platform",
        "user-agent",
        "sec-ch-ua",
        "sec-ch-ua-mobile",
        "accept",
        "sec-fetch-site",
        "sec-fetch-mode",
        "sec-fetch-dest",
        "referer",
        "accept-encoding",
        "accept-language",
        "cookie",
    ]


async def test_transport_carries_no_cookies_from_one_request_to_the_next(server):
    """Shared EH clients serve many accounts; a cookie the server set must not ride along later."""
    async with httpx.AsyncClient(
        transport=ImpersonatingTransport(), headers=browser_base_headers(), trust_env=False, timeout=5
    ) as client:
        await client.get(_url(server, "/set-cookie"))
        client.cookies.clear()
        await client.get(_url(server))

    assert _values(server.seen[1], "cookie") == []


async def test_httpx_follows_redirects_and_sends_the_cookie_it_received(server):
    """curl must not follow redirects itself, or httpx's cookie jar and history would be bypassed."""
    async with browser_client(timeout=5, follow_redirects=True) as client:
        resp = await client.get(_url(server, "/redirect"))

    assert resp.url.path == "/final"
    assert len(resp.history) == 1
    assert [record["path"] for record in server.seen] == ["/redirect", "/final"]
    assert _values(server.seen[1], "cookie") == ["sk=abc"]


async def test_compressed_bodies_arrive_decoded_without_content_encoding(server):
    """curl decodes; if Content-Encoding reached httpx it would try to decode the body again."""
    async with browser_client(timeout=5) as client:
        resp = await client.get(_url(server, "/gzip"))

    assert resp.content == b"decoded body"
    assert "content-encoding" not in resp.headers


async def test_repeated_response_headers_are_all_kept(server):
    async with browser_client(timeout=5) as client:
        resp = await client.get(_url(server))

    assert resp.headers.get_list("x-multi") == ["1", "2"]


async def test_post_bodies_reach_the_server_unchanged(server):
    async with browser_client(timeout=5) as client:
        await client.post(_url(server, "/json"), json={"method": "showpage", "page": 1})
        await client.post(_url(server, "/form"), data={"UserName": "u", "PassWord": "p"})
        await client.post(_url(server, "/upload"), files={"sfile": ("a.jpg", b"\xff\xd8\xff", "image/jpeg")})

    json_record, form_record, upload_record = server.seen
    assert json.loads(json_record["body"]) == {"method": "showpage", "page": 1}
    assert form_record["body"] == b"UserName=u&PassWord=p"
    assert b"\xff\xd8\xff" in upload_record["body"]
    assert _values(upload_record, "content-type")[0].startswith("multipart/form-data; boundary=")


# ---------------------------------------------------------------------------
# Errors map onto the httpx exceptions the callers already catch
# ---------------------------------------------------------------------------


async def test_stalled_server_raises_read_timeout_even_on_a_reused_connection(server):
    """curl reports CONNECT_TIME 0 on a pooled connection; that must not become ConnectTimeout."""
    async with browser_client() as client:
        await client.get(_url(server), timeout=5)  # opens the pooled connection
        with pytest.raises(httpx.ReadTimeout):
            await client.get(_url(server, "/stall"), timeout=1)


async def test_refused_connection_raises_connect_error_not_tls_handshake_error():
    async with browser_client(timeout=5) as client:
        with pytest.raises(httpx.ConnectError) as excinfo:
            await client.get("http://127.0.0.1:1/")

    assert not isinstance(excinfo.value, TLSHandshakeError)


async def test_failed_tls_handshake_raises_tls_handshake_error(server):
    """https:// to a plain-HTTP port fails inside the handshake (curl error 35)."""
    async with browser_client(timeout=5) as client:
        with pytest.raises(TLSHandshakeError):
            await client.get(f"https://127.0.0.1:{server.server_port}/")


def test_certificate_failure_is_never_a_tls_handshake_error():
    """The EH fallback retries on TLSHandshakeError; a bad certificate must not qualify."""
    request = httpx.Request("GET", "https://example.test/")

    error = _to_httpx_error(CurlError("certificate", code=CurlECode.PEER_FAILED_VERIFICATION), None, request)

    assert type(error) is httpx.ConnectError


# ---------------------------------------------------------------------------
# Lifecycle and event loops
# ---------------------------------------------------------------------------


async def test_cancelled_request_leaves_no_handle_in_the_curl_multi(server):
    transport = ImpersonatingTransport()
    async with httpx.AsyncClient(transport=transport, headers=browser_base_headers(), trust_env=False) as client:
        task = asyncio.create_task(client.get(_url(server, "/stall"), timeout=10))
        await asyncio.sleep(0.3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert transport._acurl._curl2future == {}
        resp = await client.get(_url(server), timeout=5)  # the transport still works afterwards

    assert resp.status_code == 200


def test_transport_works_under_uvloop(server):
    """The API runs under uvicorn's uvloop; curl_cffi drives its sockets through add_reader."""
    uvloop = pytest.importorskip("uvloop")

    async def fetch():
        async with browser_client(timeout=5) as client:
            return (await client.get(_url(server))).status_code

    assert uvloop.run(fetch()) == 200


async def test_browser_client_routes_every_request_through_the_impersonating_transport():
    client = browser_client()
    try:
        assert isinstance(client._transport, ImpersonatingTransport)
        # With trust_env on, httpx would mount proxy transports from the environment around ours.
        assert client._trust_env is False
        assert not client._mounts
        assert client.headers["User-Agent"] == BROWSER_USER_AGENT
    finally:
        await client.aclose()


# ---------------------------------------------------------------------------
# The header profile cannot drift from the impersonation target
# ---------------------------------------------------------------------------


async def test_browser_profile_matches_what_curl_cffi_sends_for_the_target(server):
    """UA, client hints and TLS must name one Chrome release; compare with curl_cffi's own headers."""
    from curl_cffi.requests import AsyncSession

    async with AsyncSession(impersonate=BROWSER_TARGET) as session:
        await session.get(_url(server))

    theirs = {name.lower(): value for name, value in server.seen[0]["headers"]}
    ours = {name.lower(): value for name, value in browser_base_headers().items()}
    assert ours["sec-ch-ua"] == theirs["sec-ch-ua"]
    assert ours["sec-ch-ua-mobile"] == theirs["sec-ch-ua-mobile"]
    assert (
        re.search(r"Chrome/[\d.]+", ours["user-agent"]).group()
        == re.search(r"Chrome/[\d.]+", theirs["user-agent"]).group()
    )
    assert ours["accept-encoding"] == theirs["accept-encoding"]
    assert ours["accept-language"] == theirs["accept-language"]
    assert browser_headers("document", site="none")["Accept"] == theirs["accept"]
