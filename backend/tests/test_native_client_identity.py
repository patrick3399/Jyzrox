"""Native E-Hentai, Pixiv and Fanbox requests present the central client identities.

Browser requests go through services.browser_http (curl_cffi as Chrome); the
Pixiv app path keeps plain httpx / pixivpy3 with the Pixiv iOS app identity.
Requests are captured at the transport (httpx.MockTransport, or a requests
adapter for pixivpy3), so the assertions see the headers actually sent after
client defaults and per-request headers are merged. The transport each client
was built with is recorded before the swap, which tells a Chrome client from a
plain one. Header order and the TLS fingerprint are covered in test_browser_http.
"""

import re
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import requests
from requests.adapters import BaseAdapter

from core.client_identity import (
    BROWSER_TARGET,
    BROWSER_USER_AGENT,
    PIXIV_APP_REFERER,
    browser_base_headers,
    browser_headers,
    pixiv_app_headers,
)
from services.browser_http import ImpersonatingTransport

_RealAsyncClient = httpx.AsyncClient
_JPEG = b"\xff\xd8\xff" + b"\x00" * 200
_FANBOX_ACCEPT = "application/json, text/plain, */*"


class _Recorder:
    """Supplies an httpx.AsyncClient subclass that records every request it sends."""

    def __init__(self, respond=None):
        self.requests: list[httpx.Request] = []
        self.transports: list = []  # what each client was built with, before the swap
        self._respond = respond or (lambda request: httpx.Response(200, content=_JPEG))
        recorder = self

        class _RecordingAsyncClient(_RealAsyncClient):
            def __init__(self, *args, **kwargs):
                recorder.transports.append(kwargs.get("transport"))
                kwargs["transport"] = httpx.MockTransport(recorder._handle)
                super().__init__(*args, **kwargs)

        self.client_class = _RecordingAsyncClient

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._respond(request)

    def assert_all_impersonate_chrome(self) -> None:
        assert self.transports
        for transport in self.transports:
            assert isinstance(transport, ImpersonatingTransport)


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


def _assert_chrome(request: httpx.Request, kind, site, *, referer=None, origin=None, accept=None) -> None:
    """Chrome's base headers plus exactly this kind's per-request headers."""
    expected = {
        **browser_base_headers(),
        **browser_headers(kind, site=site, referer=referer, origin=origin, accept=accept),
    }
    for name, value in expected.items():
        assert request.headers.get(name) == value, name
    if kind != "document":
        assert "Upgrade-Insecure-Requests" not in request.headers
        assert "Sec-Fetch-User" not in request.headers
    if referer is None:
        assert "Referer" not in request.headers
    if origin is None:
        assert "Origin" not in request.headers


def _assert_pixiv_app_identity(headers) -> None:
    for name, value in pixiv_app_headers().items():
        assert headers[name] == value, name


# ---------------------------------------------------------------------------
# The identities themselves
# ---------------------------------------------------------------------------


def test_browser_identity_claims_the_impersonated_chrome_release():
    """UA and client hints must name the release whose TLS and HTTP/2 the transport sends."""
    major = BROWSER_TARGET.removeprefix("chrome")
    assert re.fullmatch(r"\d+", major)
    expected_ua = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Chrome/{major}.0.0.0 Safari/537.36"
    )
    assert expected_ua == BROWSER_USER_AGENT
    base = browser_base_headers()
    assert f'"Chromium";v="{major}"' in base["sec-ch-ua"]
    assert f'"Google Chrome";v="{major}"' in base["sec-ch-ua"]
    assert base["sec-ch-ua-platform"] == '"Windows"'  # agrees with the UA's Windows NT token


def test_identity_header_dicts_are_not_shared_between_callers():
    """A caller that edits its headers must not change what the next caller gets."""
    for factory in (browser_base_headers, lambda: browser_headers("image", site="cross-site"), pixiv_app_headers):
        edited = factory()
        for name in edited:
            edited[name] = "edited"
        assert "edited" not in factory().values()


# ---------------------------------------------------------------------------
# E-Hentai
# ---------------------------------------------------------------------------


def _eh_respond(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("api.php"):
        return httpx.Response(200, json={})
    if request.url.host.startswith("upld."):
        return httpx.Response(200, text="<html>" + "x" * 200 + "</html>")
    return httpx.Response(200, content=_JPEG)


@pytest.fixture
async def eh_recorder(monkeypatch):
    """EH shared clients built fresh through a recorder, closed afterwards."""
    import services.eh_client as eh

    recorder = _Recorder(_eh_respond)
    monkeypatch.setattr(httpx, "AsyncClient", recorder.client_class)
    for name in ("_shared_http", "_shared_img_http", "_shared_http_weak_dh", "_shared_img_http_weak_dh"):
        monkeypatch.setattr(eh, name, None)
    yield recorder
    await eh.shutdown_shared_clients()


@pytest.mark.parametrize("factory", ["_get_shared_http", "_get_shared_img_http"])
async def test_eh_primary_shared_clients_connect_as_chrome(eh_recorder, factory):
    import services.eh_client as eh

    getattr(eh, factory)()

    eh_recorder.assert_all_impersonate_chrome()


@pytest.mark.parametrize("factory", ["_get_shared_http_weak_dh", "_get_shared_img_http_weak_dh"])
async def test_eh_tls_fallback_clients_stay_on_plain_httpx_with_chrome_headers(eh_recorder, factory):
    """The fallback exists for H@H nodes whose TLS Chrome's handshake cannot complete."""
    import services.eh_client as eh

    client = getattr(eh, factory)()

    assert eh_recorder.transports == [None]
    for name, value in browser_base_headers().items():
        assert client.headers[name] == value


async def test_eh_page_requests_are_chrome_navigations_with_account_cookies(eh_recorder):
    from services.eh_client import EhClient

    async with EhClient(cookies={"ipb_member_id": "1"}) as client:
        await client._http_get("https://e-hentai.org/g/1/abcdef/")

    request = eh_recorder.requests[0]
    _assert_chrome(request, "document", "none")
    assert "ipb_member_id=1" in request.headers["Cookie"]


@pytest.mark.parametrize(
    ("use_ex", "origin", "site"),
    [(False, "https://e-hentai.org", "same-site"), (True, "https://exhentai.org", "same-origin")],
)
async def test_eh_api_calls_are_chrome_fetches_from_the_gallery_page(eh_recorder, use_ex, origin, site):
    """api.php is called by the page's script; it used to go out with navigation headers."""
    from services.eh_client import EhClient

    async with EhClient(cookies={"ipb_member_id": "1"}, use_ex=use_ex) as client:
        await client._api({"method": "gdata", "gidlist": [[1, "abcdef"]], "namespace": 1})

    request = eh_recorder.requests[0]
    assert request.method == "POST"
    _assert_chrome(request, "fetch", site, origin=origin, referer=f"{origin}/")
    assert request.headers["Content-Type"] == "application/json"


async def test_eh_image_search_upload_is_a_chrome_form_post(eh_recorder):
    from services.eh_client import EhClient

    async with EhClient(cookies={"ipb_member_id": "1"}) as client:
        await client.image_search(_JPEG, "a.jpg")

    request = eh_recorder.requests[0]
    assert request.url.host == "upld.e-hentai.org"
    _assert_chrome(request, "document", "same-site", origin="https://e-hentai.org", referer="https://e-hentai.org/")


@pytest.mark.parametrize("use_ex", [False, True])
async def test_eh_image_fetches_are_chrome_image_loads_with_the_site_referer(eh_recorder, use_ex):
    """H@H image requests used to carry no Referer at all."""
    from services.eh_client import EhClient

    base = "https://exhentai.org" if use_ex else "https://e-hentai.org"
    async with EhClient(cookies={"ipb_member_id": "1"}, use_ex=use_ex) as client:
        await client._img_get("https://abcd.hath.network:1234/h/abc/keystamp=1/1.jpg")

    _assert_chrome(eh_recorder.requests[0], "image", "cross-site", referer=f"{base}/")


async def test_eh_plugin_image_proxy_is_a_chrome_image_load_with_account_cookies(monkeypatch):
    """It used to send httpx's default python-httpx User-Agent next to the account cookies."""
    from plugins.builtin.ehentai.browse import EhBrowsePlugin

    recorder = _Recorder()
    monkeypatch.setattr(httpx, "AsyncClient", recorder.client_class)

    await EhBrowsePlugin().proxy_image("https://ehgt.org/t/00/01.jpg", {"ipb_member_id": "1"})

    recorder.assert_all_impersonate_chrome()
    request = recorder.requests[0]
    _assert_chrome(request, "image", "cross-site", referer="https://e-hentai.org/")
    assert "ipb_member_id=1" in request.headers["Cookie"]


async def test_eh_thumbnail_proxy_is_a_chrome_image_load(client, mock_redis):
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
    recorder.assert_all_impersonate_chrome()
    _assert_chrome(recorder.requests[0], "image", "cross-site", referer="https://e-hentai.org/")


async def test_eh_password_login_requests_are_chrome_navigations(client):
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
    recorder.assert_all_impersonate_chrome()
    forum, eh_home, ex_home = recorder.requests
    _assert_chrome(
        forum,
        "document",
        "same-origin",
        origin="https://forums.e-hentai.org",
        referer="https://forums.e-hentai.org/index.php?act=Login&CODE=00",
    )
    assert (eh_home.url.host, ex_home.url.host) == ("e-hentai.org", "exhentai.org")
    _assert_chrome(eh_home, "document", "none")
    _assert_chrome(ex_home, "document", "none")


# ---------------------------------------------------------------------------
# Fanbox
# ---------------------------------------------------------------------------


async def test_fanbox_api_calls_are_chrome_fetches_and_media_are_image_loads(monkeypatch, tmp_path):
    """Fanbox used to send a bare "Mozilla/5.0" on every request."""
    from plugins.builtin.fanbox.policy import FanboxDownloadPolicy
    from plugins.builtin.fanbox.source import FanboxSourcePlugin

    media_url = "https://downloads.fanbox.cc/images/post/42/1.jpeg"
    post = {
        "id": "42",
        "title": "t",
        "feeRequired": 0,
        "creatorId": "artist",
        "publishedDatetime": "2026-07-11T00:00:00+00:00",
        "body": {"images": [{"originalUrl": media_url}]},
    }

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/post.info":
            return httpx.Response(200, json={"body": post})
        if request.url.host == "downloads.fanbox.cc":
            return httpx.Response(200, content=_JPEG, headers={"content-type": "image/jpeg"})
        return httpx.Response(200, json={"body": []})

    recorder = _Recorder(respond)
    monkeypatch.setattr(httpx, "AsyncClient", recorder.client_class)
    plugin = FanboxSourcePlugin()

    result = await plugin.download(
        "https://www.fanbox.cc/@artist/posts/42", tmp_path, credentials={"fanboxsessid": "s"}
    )
    await plugin.discover_posts("https://www.fanbox.cc/@artist", None, FanboxDownloadPolicy(), None)

    assert result.downloaded == 1
    recorder.assert_all_impersonate_chrome()
    post_info, media, paginate = recorder.requests
    for api_request in (post_info, paginate):
        _assert_chrome(
            api_request,
            "fetch",
            "same-site",
            origin="https://www.fanbox.cc",
            referer="https://www.fanbox.cc/",
            accept=_FANBOX_ACCEPT,
        )
    assert str(media.url) == media_url
    _assert_chrome(media, "image", "same-site", referer="https://www.fanbox.cc/")
    assert "FANBOXSESSID=s" in post_info.headers["Cookie"]


# ---------------------------------------------------------------------------
# Pixiv — anonymous web paths connect as Chrome
# ---------------------------------------------------------------------------


async def test_pixiv_public_ajax_requests_are_chrome_fetches(monkeypatch):
    """The public ajax fallback used to claim Chrome/124 over Python's TLS."""
    from plugins.builtin.pixiv._browse import _fetch_illust_public

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/pages"):
            return httpx.Response(200, json={"error": False, "body": []})
        return httpx.Response(200, json={"error": False, "body": {"illustId": "1", "urls": {}}})

    recorder = _Recorder(respond)
    monkeypatch.setattr(httpx, "AsyncClient", recorder.client_class)

    await _fetch_illust_public(1)

    recorder.assert_all_impersonate_chrome()
    assert [request.url.path for request in recorder.requests] == ["/ajax/illust/1", "/ajax/illust/1/pages"]
    for request in recorder.requests:
        _assert_chrome(request, "fetch", "same-origin", referer="https://www.pixiv.net/")


async def test_pixiv_public_ranking_is_a_chrome_fetch(client):
    recorder = _Recorder(lambda request: httpx.Response(200, json={"contents": []}))

    with (
        patch("plugins.builtin.pixiv._browse.get_credential", new_callable=AsyncMock, return_value=None),
        patch("httpx.AsyncClient", recorder.client_class),
    ):
        resp = await client.get("/api/pixiv/ranking", params={"mode": "daily"})

    assert resp.status_code == 200
    recorder.assert_all_impersonate_chrome()
    assert recorder.requests[0].url.path == "/ranking.php"
    _assert_chrome(recorder.requests[0], "fetch", "same-origin", referer="https://www.pixiv.net/")


async def test_pixiv_anonymous_image_fallback_is_a_chrome_image_load(client):
    """Without an account, pximg is fetched as Chrome, not with httpx's default UA."""
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
    recorder.assert_all_impersonate_chrome()
    _assert_chrome(recorder.requests[0], "image", "cross-site", referer="https://www.pixiv.net/")


# ---------------------------------------------------------------------------
# Pixiv — account paths keep one app identity on Python's TLS
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
    # The app path deliberately keeps plain httpx: no Chrome TLS under an iOS app UA.
    assert recorder.transports == [None]


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
    assert recorder.transports == [None]


async def test_pixiv_cookie_login_uses_chrome_for_the_web_session_and_the_app_for_the_token(client):
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
    web_transport, token_transport = recorder.transports
    assert web.url.host == "accounts.pixiv.net"
    assert isinstance(web_transport, ImpersonatingTransport)
    _assert_chrome(web, "document", "none")
    assert token.url.host == "oauth.secure.pixiv.net"
    assert token_transport is None
    _assert_pixiv_app_identity(token.headers)
