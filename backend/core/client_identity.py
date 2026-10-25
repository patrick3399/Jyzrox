"""Client identities the native E-Hentai, Pixiv and Fanbox paths present upstream.

gallery-dl downloads are not covered here: their identity comes from
gallery-dl's own ``browser`` / ``user-agent`` options and the egress personas
(ADR 0022).
"""

# One desktop browser, Firefox on Windows, for every native web and image
# request. Firefox sends no User-Agent client hints, so an httpx request with a
# Firefox UA and no ``sec-ch-ua*`` headers looks like the real browser. A Chrome
# UA without them is a well-known bot tell, and faking them would claim Chrome
# over a TLS handshake that is not Chrome's. ``Sec-Fetch-*`` is not faked
# either: its values depend on how each request was started. Accept-Encoding
# stays httpx's own, because advertising an encoding it cannot decode breaks
# the response.
#
# The version is static on purpose: bump it when Firefox stable moves on
# (LATEST_FIREFOX_VERSION in product-details.mozilla.org/1.0/firefox_versions.json).
# Mozilla moved from four-week to two-week releases in September 2026, so a
# version computed from the date drifts.
_FIREFOX_MAJOR = 158

BROWSER_USER_AGENT = (
    f"Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:{_FIREFOX_MAJOR}.0) Gecko/20100101 Firefox/{_FIREFOX_MAJOR}.0"
)
BROWSER_ACCEPT_LANGUAGE = "en-US,en;q=0.9"

# Firefox's Accept per request kind (MDN "List of default Accept values").
ACCEPT_DOCUMENT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
ACCEPT_IMAGE = "image/avif,image/jxl,image/webp,image/png,image/svg+xml,image/*;q=0.8,*/*;q=0.5"
ACCEPT_FETCH = "*/*"


def browser_headers(accept: str = ACCEPT_FETCH) -> dict[str, str]:
    """Return a new dict of the browser identity headers with the given Accept."""
    return {"User-Agent": BROWSER_USER_AGENT, "Accept": accept, "Accept-Language": BROWSER_ACCEPT_LANGUAGE}


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
