"""Client identities the native E-Hentai, Pixiv and Fanbox paths present upstream.

gallery-dl downloads are not covered here: their identity comes from
gallery-dl's own ``browser`` / ``user-agent`` options and the egress personas
(ADR 0022).
"""

from typing import Literal

# The browser is one curl_cffi impersonation target. services.browser_http
# sends that target's TLS ClientHello, HTTP/2 settings and header order, and
# the headers below claim the same Chrome release, client hints included.
# Bump BROWSER_TARGET together with curl_cffi and take the new release's
# sec-ch-ua GREASE brand; a test compares both with what curl_cffi itself
# sends for the target. The platform is Windows rather than the target's macOS
# capture: Chrome's TLS and HTTP/2 fingerprints do not change with the OS.
BROWSER_TARGET = "chrome150"
_CHROME_MAJOR = BROWSER_TARGET.removeprefix("chrome")
_SEC_CH_UA = f'"Not;A=Brand";v="8", "Chromium";v="{_CHROME_MAJOR}", "Google Chrome";v="{_CHROME_MAJOR}"'

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    f"Chrome/{_CHROME_MAJOR}.0.0.0 Safari/537.36"
)
BROWSER_ACCEPT_LANGUAGE = "en-US,en;q=0.9"

# Chrome's Accept per request kind.
ACCEPT_DOCUMENT = (
    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,"
    "application/signed-exchange;v=b3;q=0.7"
)
ACCEPT_IMAGE = "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8"
ACCEPT_FETCH = "*/*"

RequestKind = Literal["document", "fetch", "image"]
FetchSite = Literal["none", "same-origin", "same-site", "cross-site"]


def browser_base_headers() -> dict[str, str]:
    """Return a new dict of the headers Chrome sends on every request."""
    return {
        "sec-ch-ua": _SEC_CH_UA,
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "User-Agent": BROWSER_USER_AGENT,
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": BROWSER_ACCEPT_LANGUAGE,
    }


def browser_headers(
    kind: RequestKind,
    *,
    site: FetchSite,
    referer: str | None = None,
    origin: str | None = None,
    accept: str | None = None,
) -> dict[str, str]:
    """Return a new dict of the per-request headers for one kind of Chrome request.

    ``document`` is a top-level navigation (page loads, form posts), ``fetch`` a
    script's fetch()/XHR such as a JSON API, ``image`` an <img> load. ``site``
    is Sec-Fetch-Site as seen from the page that would make the request. The
    transport puts headers in Chrome's order, so dict order does not matter.
    """
    if kind == "document":
        headers = {
            "Upgrade-Insecure-Requests": "1",
            "Accept": accept or ACCEPT_DOCUMENT,
            "Sec-Fetch-Site": site,
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-User": "?1",
            "Sec-Fetch-Dest": "document",
            "Priority": "u=0, i",
        }
    elif kind == "fetch":
        headers = {
            "Accept": accept or ACCEPT_FETCH,
            "Sec-Fetch-Site": site,
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
            "Priority": "u=1, i",
        }
    else:
        headers = {
            "Accept": accept or ACCEPT_IMAGE,
            "Sec-Fetch-Site": site,
            "Sec-Fetch-Mode": "no-cors",
            "Sec-Fetch-Dest": "image",
            "Priority": "i",
        }
    if referer:
        headers["Referer"] = referer
    if origin:
        headers["Origin"] = origin
    return headers


# The Pixiv iOS app, for every app-api, OAuth and pximg request made with a
# Pixiv account. Same app version and device as gallery-dl's Pixiv app API, so
# an account presents one client whichever downloader runs the job. Accept is
# pinned because pixivpy3's cloudscraper session would otherwise pick a random
# browser's value per client; "en" also selects English tag translations.
_PIXIV_APP_VERSION = "7.19.1"
_PIXIV_IOS_VERSION = "16.7.2"

PIXIV_APP_REFERER = "https://app-api.pixiv.net/"


def pixiv_app_headers() -> dict[str, str]:
    """Return a new dict of the Pixiv app identity headers."""
    return {
        "User-Agent": f"PixivIOSApp/{_PIXIV_APP_VERSION} (iOS {_PIXIV_IOS_VERSION}; iPhone12,8)",
        "App-OS": "ios",
        "App-OS-Version": _PIXIV_IOS_VERSION,
        "App-Version": _PIXIV_APP_VERSION,
        "Accept": "*/*",
        "Accept-Language": "en",
    }
