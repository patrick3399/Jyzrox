"""Native E-Hentai, Pixiv and Fanbox requests present the central client identities.

Requests are captured at the transport (httpx.MockTransport, or a requests
adapter for pixivpy3), so the assertions see the headers actually sent after
client defaults and per-request headers are merged.
"""

import re
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import requests
from requests.adapters import BaseAdapter

from core.client_identity import (
    ACCEPT_DOCUMENT,
    ACCEPT_FETCH,
    ACCEPT_IMAGE,
    BROWSER_ACCEPT_LANGUAGE,
    BROWSER_USER_AGENT,
    PIXIV_APP_REFERER,
    browser_headers,
    pixiv_app_headers,
)

_RealAsyncClient = httpx.AsyncClient
_JPEG = b"\xff\xd8\xff" + b"\x00" * 16


class _Recorder:
    """Supplies an httpx.AsyncClient subclass that records every request it sends."""

    def __init__(self, respond=None):
        self.requests: list[httpx.Request] = []
        self._respond = respond or (lambda request: httpx.Response(200, content=_JPEG))
        recorder = self

        class _RecordingAsyncClient(_RealAsyncClient):
            def __init__(self, *args, **kwargs):
                kwargs["transport"] = httpx.MockTransport(recorder._handle)
                super().__init__(*args, **kwargs)

        self.client_class = _RecordingAsyncClient

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._respond(request)


class _RecordingAdapter(BaseAdapter):
    """requests transport adapter that records pixivpy3's prepared requests."""

    def __init__(self, sent: list, payload: bytes):
        super().__init__()
        self._sent = sent
        self._payload = payload

    def send(self, request, **kwargs):
        self._sent.append(request)
        response = requests.Response()
        response.status_code = 200
        response._content = self._payload
        response.headers["Content-Type"] = "application/json"
        response.request = request
        response.url = request.url
        return response

    def close(self):
        pass


# One payload that satisfies pixivpy3's auth() and user_detail() parsing.
_PIXIV_APP_PAYLOAD = (
    b'{"response": {"access_token": "access", "refresh_token": "refresh", "user": {"id": 7}},'
    b' "user": {"id": 7, "name": "PixivUser"}}'
)


def _recording_app_api(sent: list):
    """Wrap the real new_app_api so its requests go to a recording adapter."""
    from services.pixiv_client import new_app_api

    def factory():
        api = new_app_api()
        api.requests.mount("https://", _RecordingAdapter(sent, _PIXIV_APP_PAYLOAD))
        return api

    return factory


def _assert_browser_identity(request: httpx.Request, accept: str) -> None:
    assert request.headers["User-Agent"] == BROWSER_USER_AGENT
    assert request.headers["Accept"] == accept
    assert request.headers["Accept-Language"] == BROWSER_ACCEPT_LANGUAGE
    assert not [name for name in request.headers if name.lower().startswith("sec-ch-ua")]


def _assert_pixiv_app_identity(headers) -> None:
    for name, value in pixiv_app_headers().items():
        assert headers[name] == value, name


# ---------------------------------------------------------------------------
# The identities themselves
# ---------------------------------------------------------------------------


def test_browser_identity_claims_one_firefox_release_without_client_hints():
    """rv: and Firefox/ must name the same release, and Firefox sends no sec-ch-ua*."""
    match = re.fullmatch(
        r"Mozilla/5\.0 \(Windows NT 10\.0; Win64; x64; rv:(\d+)\.0\) Gecko/20100101 Firefox/(\d+)\.0",
        BROWSER_USER_AGENT,
    )
    assert match is not None
    assert match.group(1) == match.group(2)
    assert not [name for name in browser_headers() if name.lower().startswith("sec-ch")]


def test_identity_header_dicts_are_not_shared_between_callers():
    """A caller that edits its headers must not change what the next caller gets."""
    browser = browser_headers()
    browser["User-Agent"] = "edited"
    app = pixiv_app_headers()
    app["User-Agent"] = "edited"

    assert browser_headers()["User-Agent"] == BROWSER_USER_AGENT
    assert pixiv_app_headers()["User-Agent"] != "edited"


# ---------------------------------------------------------------------------
# E-Hentai
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("factory", "accept"),
    [
        ("_get_shared_http", ACCEPT_DOCUMENT),
        ("_get_shared_img_http", ACCEPT_IMAGE),
        ("_get_shared_http_weak_dh", ACCEPT_DOCUMENT),
        ("_get_shared_img_http_weak_dh", ACCEPT_IMAGE),
    ],
)
async def test_eh_shared_clients_send_central_browser_identity(monkeypatch, factory, accept):
    """Every EhClient request goes through these four clients, weak-DH fallbacks included."""
    import services.eh_client as eh

    recorder = _Recorder()
    monkeypatch.setattr(httpx, "AsyncClient", recorder.client_class)
    for name in ("_shared_http", "_shared_img_http", "_shared_http_weak_dh", "_shared_img_http_weak_dh"):
        monkeypatch.setattr(eh, name, None)

    client = getattr(eh, factory)()
    try:
        await client.get("https://e-hentai.org/g/1/abcdef/")
    finally:
        await client.aclose()

    _assert_browser_identity(recorder.requests[0], accept)


async def test_eh_plugin_image_proxy_sends_browser_identity_with_account_cookies(monkeypatch):
    """It used to send httpx's default python-httpx User-Agent next to the account cookies."""
    from plugins.builtin.ehentai.browse import EhBrowsePlugin

    recorder = _Recorder()
    monkeypatch.setattr(httpx, "AsyncClient", recorder.client_class)

    await EhBrowsePlugin().proxy_image("https://ehgt.org/t/00/01.jpg", {"ipb_member_id": "1"})

    request = recorder.requests[0]
    _assert_browser_identity(request, ACCEPT_IMAGE)
    assert "ipb_member_id=1" in request.headers["Cookie"]


async def test_eh_thumbnail_proxy_sends_browser_identity(client, mock_redis):
    """The thumbnail CDN fetch used to send httpx's default User-Agent."""
    mock_redis.get = AsyncMock(return_value=None)
    recorder = _Recorder()

    with (
        patch("plugins.builtin.ehentai.browse._is_private", return_value=True),
        patch("plugins.builtin.ehentai.browse.get_credential", new_callable=AsyncMock, return_value=None),
        patch("httpx.AsyncClient", recorder.client_class),
    ):
        resp = await client.get("/api/eh/thumb-proxy", params={"url": "https://ehgt.org/t/00/01.jpg"})

    assert resp.status_code == 200
    request = recorder.requests[0]
    _assert_browser_identity(request, ACCEPT_IMAGE)
    assert request.headers["Referer"] == "https://e-hentai.org/"


async def test_eh_password_login_sends_browser_identity_on_every_request(client):
    """Forum login, e-hentai.org and exhentai.org must all see the account's one browser."""

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.host == "forums.e-hentai.org":
            return httpx.Response(
                200,
                headers=[("set-cookie", "ipb_member_id=1; path=/"), ("set-cookie", "ipb_pass_hash=hash; path=/")],
            )
        return httpx.Response(200)

    recorder = _Recorder(respond)
    eh_client = MagicMock()
    eh_client.__aenter__ = AsyncMock(return_value=eh_client)
    eh_client.__aexit__ = AsyncMock(return_value=False)
    eh_client.check_cookies = AsyncMock(return_value=True)
    eh_client.get_account_info = AsyncMock(return_value={})

    with (
        patch("routers.settings.set_credential", new_callable=AsyncMock),
        patch("routers.settings.EhClient", return_value=eh_client),
        patch("httpx.AsyncClient", recorder.client_class),
    ):
        resp = await client.post(
            "/api/settings/credentials/ehentai/login", json={"username": "user", "password": "pass"}
        )

    assert resp.status_code == 200
    assert [request.url.host for request in recorder.requests] == [
        "forums.e-hentai.org",
        "e-hentai.org",
        "exhentai.org",
    ]
    for request in recorder.requests:
        _assert_browser_identity(request, ACCEPT_DOCUMENT)


# ---------------------------------------------------------------------------
# Fanbox
# ---------------------------------------------------------------------------


async def test_fanbox_requests_send_full_browser_user_agent(monkeypatch, tmp_path):
    """Fanbox used to send a bare "Mozilla/5.0", the most bot-like UA in the codebase."""
    from plugins.builtin.fanbox.policy import FanboxDownloadPolicy
    from plugins.builtin.fanbox.source import FanboxSourcePlugin

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/post.info":
            return httpx.Response(401)
        return httpx.Response(200, json={"body": []})

    recorder = _Recorder(respond)
    monkeypatch.setattr(httpx, "AsyncClient", recorder.client_class)
    plugin = FanboxSourcePlugin()

    await plugin.download("https://www.fanbox.cc/@artist/posts/42", tmp_path, credentials={"fanboxsessid": "s"})
    await plugin.discover_posts("https://www.fanbox.cc/@artist", None, FanboxDownloadPolicy(), None)

    assert [request.url.path for request in recorder.requests] == ["/post.info", "/post.paginateCreator"]
    for request in recorder.requests:
        _assert_browser_identity(request, "application/json, text/plain, */*")
        assert request.headers["Referer"] == "https://www.fanbox.cc/"


# ---------------------------------------------------------------------------
# Pixiv — anonymous web paths use the browser identity
# ---------------------------------------------------------------------------


async def test_pixiv_public_ajax_requests_send_current_browser_identity(monkeypatch):
    """The public ajax fallback used to claim Chrome/124."""
    from plugins.builtin.pixiv._browse import _fetch_illust_public

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/pages"):
            return httpx.Response(200, json={"error": False, "body": []})
        return httpx.Response(200, json={"error": False, "body": {"illustId": "1", "urls": {}}})

    recorder = _Recorder(respond)
    monkeypatch.setattr(httpx, "AsyncClient", recorder.client_class)

    await _fetch_illust_public(1)

    assert [request.url.path for request in recorder.requests] == ["/ajax/illust/1", "/ajax/illust/1/pages"]
    for request in recorder.requests:
        _assert_browser_identity(request, ACCEPT_FETCH)
        assert request.headers["Referer"] == "https://www.pixiv.net/"


async def test_pixiv_anonymous_image_fallback_sends_browser_identity(client):
    """Without an account, pximg is fetched as the browser, not with httpx's default UA."""
    recorder = _Recorder()

    with (
        patch("services.cache.get_pixiv_image_cache", new_callable=AsyncMock, return_value=None),
        patch("services.cache.set_pixiv_image_cache", new_callable=AsyncMock),
        patch("core.rate_limit.check_rate_limit", new_callable=AsyncMock),
        patch("plugins.builtin.pixiv._browse.get_credential", new_callable=AsyncMock, return_value=None),
        patch("httpx.AsyncClient", recorder.client_class),
    ):
        resp = await client.get(
            "/api/pixiv/image-proxy",
            params={"url": "https://i.pximg.net/img-original/img/2024/01/01/00/00/00/1_p0.jpg"},
        )

    assert resp.status_code == 200
    request = recorder.requests[0]
    _assert_browser_identity(request, ACCEPT_IMAGE)
    assert request.headers["Referer"] == "https://www.pixiv.net/"


# ---------------------------------------------------------------------------
# Pixiv — account paths use one app identity
# ---------------------------------------------------------------------------


async def test_pixiv_api_oauth_and_image_requests_share_one_app_identity(monkeypatch):
    """API and OAuth used pixivpy3's iOS 7.13.3 identity while images claimed Android 5.0.234."""
    import services.pixiv_client as pixiv_client

    sent: list = []
    api = _recording_app_api(sent)()
    api.auth(refresh_token="refresh")
    api.user_detail(7)

    recorder = _Recorder()
    monkeypatch.setattr(httpx, "AsyncClient", recorder.client_class)
    monkeypatch.setattr(pixiv_client, "_shared_img_http", None)
    image_client = pixiv_client._get_shared_img_http()
    try:
        await image_client.get("https://i.pximg.net/img-original/img/2024/01/01/00/00/00/1_p0.jpg")
    finally:
        await image_client.aclose()

    assert [request.url.split("?")[0] for request in sent] == [
        "https://oauth.secure.pixiv.net/auth/token",
        "https://app-api.pixiv.net/v1/user/detail",
    ]
    for headers in [request.headers for request in sent] + [recorder.requests[0].headers]:
        _assert_pixiv_app_identity(headers)
    assert recorder.requests[0].headers["Referer"] == PIXIV_APP_REFERER


async def test_pixiv_credential_verify_uses_the_app_identity_client():
    """A bare pixivpy3 client would verify the token with pixivpy3's own, older identity."""
    from plugins.builtin.pixiv._credentials import verify_pixiv_credential

    sent: list = []
    with (
        patch("services.pixiv_client.new_app_api", _recording_app_api(sent)),
        patch("pixivpy3.AppPixivAPI", side_effect=AssertionError("bare pixivpy3 client")),
    ):
        result = await verify_pixiv_credential({"refresh_token": "refresh"})

    assert result.valid is True
    assert result.username == "PixivUser"
    assert len(sent) == 2
    for request in sent:
        _assert_pixiv_app_identity(request.headers)


async def test_saving_pixiv_refresh_token_verifies_with_the_app_identity_client(client):
    sent: list = []
    with (
        patch("routers.settings.set_credential", new_callable=AsyncMock),
        patch("services.pixiv_client.new_app_api", _recording_app_api(sent)),
        patch("pixivpy3.AppPixivAPI", side_effect=AssertionError("bare pixivpy3 client")),
    ):
        resp = await client.post("/api/settings/credentials/pixiv", json={"refresh_token": "refresh"})

    assert resp.status_code == 200
    assert resp.json()["username"] == "PixivUser"
    assert len(sent) == 2
    for request in sent:
        _assert_pixiv_app_identity(request.headers)


async def test_pixiv_oauth_callback_exchanges_code_with_the_app_identity(client):
    """The code exchange claimed Android 5.0.234 while later refreshes used another app."""
    recorder = _Recorder(lambda request: httpx.Response(200, json={"refresh_token": "rt", "user": {"name": "u"}}))

    with (
        patch("routers.settings.set_credential", new_callable=AsyncMock),
        patch("httpx.AsyncClient", recorder.client_class),
    ):
        resp = await client.post(
            "/api/settings/credentials/pixiv/oauth-callback", json={"code": "code", "code_verifier": "verifier"}
        )

    assert resp.status_code == 200
    assert str(recorder.requests[0].url) == "https://oauth.secure.pixiv.net/auth/token"
    _assert_pixiv_app_identity(recorder.requests[0].headers)


async def test_pixiv_cookie_login_uses_browser_for_the_web_session_and_app_for_the_token(client):
    """The PHPSESSID request is a browser navigation; the token exchange is the app."""

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.host == "accounts.pixiv.net":
            callback = "https://app-api.pixiv.net/web/v1/users/auth/pixiv/callback?code=abc"
            return httpx.Response(302, headers={"Location": callback})
        return httpx.Response(200, json={"refresh_token": "rt", "user": {"name": "u"}})

    recorder = _Recorder(respond)
    with (
        patch("routers.settings.set_credential", new_callable=AsyncMock),
        patch("httpx.AsyncClient", recorder.client_class),
    ):
        resp = await client.post("/api/settings/credentials/pixiv/cookie", json={"phpsessid": "session"})

    assert resp.status_code == 200
    web, token = recorder.requests
    assert web.url.host == "accounts.pixiv.net"
    _assert_browser_identity(web, ACCEPT_DOCUMENT)
    assert token.url.host == "oauth.secure.pixiv.net"
    _assert_pixiv_app_identity(token.headers)
