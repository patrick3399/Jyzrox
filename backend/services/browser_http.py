"""HTTP client for native web requests that connects as Chrome.

httpx stays the API: redirects, cookies, ``raise_for_status`` and the httpx
exception types behave as before. Only the transport changes: requests go out
through curl_cffi, so the TLS ClientHello, the HTTP/2 SETTINGS and priority and
the header order are Chrome's (core.client_identity.BROWSER_TARGET), while the
header values come from core.client_identity.

Responses are read fully into memory; no native path streams.
"""

import asyncio
import math
from io import BytesIO
from typing import Any

import httpx
from curl_cffi import AsyncCurl, Curl, CurlECode, CurlError, CurlInfo, CurlMOpt, CurlOpt

from core.client_identity import BROWSER_TARGET, browser_base_headers

# curl writes these itself; forwarding httpx's copies would duplicate them.
_DROP_REQUEST_HEADERS = frozenset(
    {"host", "connection", "keep-alive", "content-length", "transfer-encoding", "upgrade", "te"}
)
# curl has already decoded the body, so httpx must not decode or size-check it again.
_DROP_RESPONSE_HEADERS = frozenset({b"content-encoding", b"content-length", b"transfer-encoding"})

# Chrome orders navigation and subresource request headers differently.
_NAVIGATION_ORDER = (
    "sec-ch-ua",
    "sec-ch-ua-mobile",
    "sec-ch-ua-platform",
    "origin",
    "content-type",
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
    "cookie",
    "priority",
)
_SUBRESOURCE_ORDER = (
    "sec-ch-ua-platform",
    "user-agent",
    "sec-ch-ua",
    "content-type",
    "sec-ch-ua-mobile",
    "accept",
    "origin",
    "sec-fetch-site",
    "sec-fetch-mode",
    "sec-fetch-dest",
    "referer",
    "accept-encoding",
    "accept-language",
    "cookie",
    "priority",
)

_CONNECT_ERRORS = frozenset(
    {
        CurlECode.COULDNT_RESOLVE_HOST,
        CurlECode.COULDNT_RESOLVE_PROXY,
        CurlECode.COULDNT_CONNECT,
        CurlECode.PEER_FAILED_VERIFICATION,
    }
)
_READ_ERRORS = frozenset({CurlECode.RECV_ERROR, CurlECode.PARTIAL_FILE, CurlECode.GOT_NOTHING})


class TLSHandshakeError(httpx.ConnectError):
    """The TLS handshake itself failed (curl error 35).

    A certificate that fails verification is a plain httpx.ConnectError, so
    nothing that falls back on this error can bypass verification.
    """


def _chrome_order(headers: list[tuple[bytes, bytes]]) -> list[tuple[bytes, bytes]]:
    navigate = any(name.lower() == b"sec-fetch-mode" and value == b"navigate" for name, value in headers)
    order = _NAVIGATION_ORDER if navigate else _SUBRESOURCE_ORDER
    rank = {name: index for index, name in enumerate(order)}
    unknown = order.index("cookie") - 0.5  # other headers go just before cookie and priority
    return sorted(headers, key=lambda item: rank.get(item[0].lower().decode("latin-1"), unknown))


def _last_header_block(raw: bytes) -> list[tuple[bytes, bytes]]:
    """Header lines of the final response in curl's header buffer (after any 1xx)."""
    block: list[tuple[bytes, bytes]] = []
    for line in raw.split(b"\r\n"):
        if line.startswith(b"HTTP/"):
            block = []
        elif b":" in line:
            name, _, value = line.partition(b":")
            block.append((name.strip(), value.strip()))
    return block


def _to_httpx_error(exc: CurlError, curl: Curl, request: httpx.Request) -> httpx.TransportError:
    code, message = exc.code, str(exc)
    if code == CurlECode.OPERATION_TIMEDOUT:
        # CONNECT_TIME is 0 on a reused connection, so ask whether the request went out.
        sent = curl.getinfo(CurlInfo.REQUEST_SIZE) > 0
        return (httpx.ReadTimeout if sent else httpx.ConnectTimeout)(message, request=request)
    if code == CurlECode.SSL_CONNECT_ERROR:
        return TLSHandshakeError(message, request=request)
    if code in _CONNECT_ERRORS:
        return httpx.ConnectError(message, request=request)
    if code == CurlECode.SEND_ERROR:
        return httpx.WriteError(message, request=request)
    if code in _READ_ERRORS:
        return httpx.ReadError(message, request=request)
    if code in (CurlECode.HTTP2, CurlECode.HTTP2_STREAM):
        return httpx.RemoteProtocolError(message, request=request)
    return httpx.TransportError(message, request=request)


class ImpersonatingTransport(httpx.AsyncBaseTransport):
    """httpx transport that sends each request through curl_cffi as ``target``.

    Every request gets a fresh curl handle, so no cookie or header state is
    carried between requests (cookies stay in httpx's jar); the shared multi
    handle still pools connections. curl does not follow redirects — httpx does.
    """

    def __init__(self, target: str = BROWSER_TARGET, *, max_connections: int | None = None) -> None:
        self._target = target
        self._max_connections = max_connections
        self._acurl: AsyncCurl | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def _multi(self) -> AsyncCurl:
        loop = asyncio.get_running_loop()
        if self._acurl is None or self._loop is not loop:
            self._acurl = AsyncCurl(loop=loop)
            self._loop = loop
            if self._max_connections:
                self._acurl.setopt(CurlMOpt.MAX_TOTAL_CONNECTIONS, self._max_connections)
        return self._acurl

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        content = await request.aread()
        acurl = self._multi()
        curl = Curl()
        body, head = BytesIO(), BytesIO()
        try:
            curl.impersonate(self._target, default_headers=False)
            curl.setopt(CurlOpt.URL, str(request.url).encode())
            if request.method == "HEAD":
                curl.setopt(CurlOpt.NOBODY, 1)
            elif request.method != "GET" or content:
                curl.setopt(CurlOpt.CUSTOMREQUEST, request.method.encode())
                curl.setopt(CurlOpt.POSTFIELDS, content)
                curl.setopt(CurlOpt.POSTFIELDSIZE, len(content))
            headers = _chrome_order(
                [
                    (name, value)
                    for name, value in request.headers.raw
                    if name.lower().decode("latin-1") not in _DROP_REQUEST_HEADERS
                ]
            )
            curl.setopt(CurlOpt.HTTPHEADER, [name + b": " + value for name, value in headers])
            # Decode exactly what the request advertised; the header keeps its Chrome position.
            encoding = next((value for name, value in headers if name.lower() == b"accept-encoding"), None)
            if encoding is not None:
                curl.setopt(CurlOpt.ACCEPT_ENCODING, encoding)
            timeout = request.extensions.get("timeout", {})
            if timeout.get("connect") is not None:
                curl.setopt(CurlOpt.CONNECTTIMEOUT_MS, max(1, int(timeout["connect"] * 1000)))
            if timeout.get("read") is not None:
                # httpx's read timeout is an inactivity timeout, not a limit on the whole transfer.
                curl.setopt(CurlOpt.LOW_SPEED_LIMIT, 1)
                curl.setopt(CurlOpt.LOW_SPEED_TIME, max(1, math.ceil(timeout["read"])))
            curl.setopt(CurlOpt.WRITEDATA, body)
            curl.setopt(CurlOpt.HEADERDATA, head)
            future = acurl.add_handle(curl)
            try:
                await future
            except CurlError:
                raise
            except BaseException:
                # Cancelled: the handle is still in the multi and must leave it.
                acurl.remove_handle(curl)
                raise
            status = curl.getinfo(CurlInfo.RESPONSE_CODE)
            http_version = curl.getinfo(CurlInfo.HTTP_VERSION)
        except CurlError as exc:
            raise _to_httpx_error(exc, curl, request) from exc
        finally:
            curl.close()
        return httpx.Response(
            status,
            headers=[
                (name, value)
                for name, value in _last_header_block(head.getvalue())
                if name.lower() not in _DROP_RESPONSE_HEADERS
            ],
            content=body.getvalue(),
            request=request,
            extensions={"http_version": b"HTTP/2" if http_version == 3 else b"HTTP/1.1"},
        )

    async def aclose(self) -> None:
        if self._acurl is not None:
            await self._acurl.close()
            self._acurl = None


def browser_client(*, max_connections: int | None = None, **kwargs: Any) -> httpx.AsyncClient:
    """httpx client that connects as Chrome; pass browser_headers(kind, ...) per request.

    trust_env is off so httpx never routes a request around this transport;
    curl itself still honours the proxy environment variables.
    """
    headers = {**browser_base_headers(), **(kwargs.pop("headers", None) or {})}
    return httpx.AsyncClient(
        transport=ImpersonatingTransport(BROWSER_TARGET, max_connections=max_connections),
        headers=headers,
        trust_env=False,
        **kwargs,
    )
