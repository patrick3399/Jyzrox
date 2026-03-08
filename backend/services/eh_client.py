"""
E-Hentai / ExHentai HTTP client.

References:
  - EhViewer EhEngine.kt
  - https://ehwiki.org/wiki/API
"""

import logging
import re
from collections import defaultdict
from typing import Any
from urllib.parse import urlencode

import httpx
from bs4 import BeautifulSoup

from core.config import settings

logger = logging.getLogger(__name__)

EH_API_URL = "https://api.e-hentai.org/api.php"
EH_BASE_URL = "https://e-hentai.org"
EX_BASE_URL = "https://exhentai.org"

CATEGORY_MASK: dict[str, int] = {
    "misc": 1,
    "doujinshi": 2,
    "manga": 4,
    "artist_cg": 8,
    "game_cg": 16,
    "image_set": 32,
    "cosplay": 64,
    "asian_porn": 128,
    "non-h": 256,
    "western": 512,
}
ALL_CATS = sum(CATEGORY_MASK.values())  # 1023

_GALLERY_URL_RE = re.compile(r"e[x\-]hentai\.org/g/(\d+)/([a-f0-9]{10})/")
_TOTAL_COUNT_RE = re.compile(r"Showing .+? of ([\d,]+)")
# Matches preview page links: /s/{ptoken}/{gid}-{page}
_PTOKEN_RE = re.compile(r"/s/([0-9a-f]{10})/(\d+)-(\d+)")
# Matches showkey in page HTML: var showkey="...";
_SHOWKEY_RE = re.compile(r'var\s+showkey\s*=\s*"([0-9a-z]+)"')
# Matches nl() call in image page HTML: return nl('PARAM')
_NL_RE = re.compile(r"return nl\('([^']+)'\)")
# Large preview: <div class="gdtl"...><a href="..."><img alt="N" src="THUMB_URL"...>
_LARGE_PREVIEW_RE = re.compile(
    r'<div class="gdtl"[^>]*>.*?<a[^>]*href="[^"]*"[^>]*>'
    r'<img[^>]*alt="(\d+)"[^>]*src="([^"]+)"',
    re.DOTALL,
)
# Normal preview: <div class="gdtm" style="...background:...url(SPRITE) -Xpx...;width:Wpx;height:Hpx">
# We extract the sprite URL, offset, width, height AND the page number from the /s/ link inside
_NORMAL_PREVIEW_RE = re.compile(
    r'<div[^>]*class="gdtm"[^>]*style="[^"]*'
    r'url\(([^)]+)\)\s*(-?\d+)px[^"]*'
    r'width:\s*(\d+)px;\s*height:\s*(\d+)px[^"]*"[^>]*>'
    r".*?/s/[0-9a-f]+/\d+-(\d+)",
    re.DOTALL,
)
# New format (2024+): <a href="/s/PTOKEN/GID-PAGE"><div style="width:Wpx;height:Hpx;background:transparent url(THUMB) OFFSETpx 0 no-repeat"></div></a>
# Order in style: width → height → background (with url + offset)
_NEW_PREVIEW_RE = re.compile(
    r'<a[^>]+href="[^"]+/s/[0-9a-f]{10}/\d+-(\d+)"[^>]*>'
    r'<div[^>]+style="[^"]*'
    r'width:\s*(\d+)px[^"]*height:\s*(\d+)px[^"]*'
    r'url\(([^)]+)\)\s*(-?\d+)px',
    re.DOTALL,
)


def _chunks(lst: list, n: int):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def _parse_gmetadata(g: dict) -> dict:
    """Normalise a single gdata API entry to our internal dict."""
    return {
        "gid": int(g["gid"]),
        "token": g["token"],
        "title": g.get("title", ""),
        "title_jpn": g.get("title_jpn", ""),
        "category": g.get("category", ""),
        "thumb": g.get("thumb", ""),
        "uploader": g.get("uploader", ""),
        "posted_at": int(g.get("posted", 0)),
        "pages": int(g.get("filecount", 0)),
        "rating": float(g.get("rating", 0)),
        "tags": g.get("tags", []),
        "expunged": bool(g.get("expunged", False)),
    }


def _detect_media_type(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


class EhClient:
    """
    Async HTTP client for E-Hentai / ExHentai.
    Use as an async context manager.

    Example:
        async with EhClient(cookies) as client:
            result = await client.search("rem")
    """

    def __init__(self, cookies: dict, use_ex: bool = False) -> None:
        self.cookies = cookies
        self.base_url = EX_BASE_URL if use_ex else EH_BASE_URL
        self._http: httpx.AsyncClient | None = None
        self._img_http: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "EhClient":
        # Inject nw=1 cookie to skip Content Warning page
        cookies = {**self.cookies, "nw": "1"}
        self._http = httpx.AsyncClient(
            cookies=cookies,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=settings.eh_request_timeout,
            follow_redirects=True,
        )
        self._img_http = httpx.AsyncClient(
            cookies=cookies,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
            },
            timeout=20,
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, *_) -> None:
        if self._img_http:
            await self._img_http.aclose()
        if self._http:
            await self._http.aclose()

    # ── Internal ─────────────────────────────────────────────────────

    async def _api(self, payload: dict) -> dict:
        api_url = f"{self.base_url}/api.php" if self.base_url == EX_BASE_URL else EH_API_URL
        resp = await self._http.post(api_url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        if data.get("error"):
            raise ValueError(f"E-H API error: {data['error']}")
        return data

    def _check_auth(self, html: str, resp: httpx.Response | None = None) -> None:
        # Sad Panda detection (ExHentai returns a tiny image instead of HTML)
        if resp is not None and len(html) < 100 and "<html" not in html.lower():
            raise PermissionError("ExHentai access denied (Sad Panda)")
        cd = resp.headers.get("content-disposition", "") if resp else ""
        if "sadpanda" in cd.lower():
            raise PermissionError("ExHentai access denied (Sad Panda)")
        # 509 bandwidth exceeded detection
        if "/509.gif" in html or "/509s.gif" in html:
            raise PermissionError("E-Hentai bandwidth limit exceeded (509)")
        if "You do not have access" in html:
            raise PermissionError("EH cookie invalid or expired")

    # ── Public API ───────────────────────────────────────────────────

    async def search(
        self,
        query: str = "",
        page: int = 0,
        category: str | None = None,
        f_cats: int | None = None,
        advance: bool = False,
        adv_search: int = 0,
        min_rating: int | None = None,
        page_from: int | None = None,
        page_to: int | None = None,
    ) -> dict:
        """
        Scrape E-H search results.
        Strategy: extract gallery IDs from HTML, then batch via gdata API.
        """
        params: dict[str, Any] = {"page": page}
        if query:
            params["f_search"] = query

        # Category bitmask: f_cats = direct bitmask, category = single category
        if f_cats is not None:
            params["f_cats"] = f_cats
        elif category and category in CATEGORY_MASK:
            params["f_cats"] = ALL_CATS ^ CATEGORY_MASK[category]

        # Advanced search flags (EHViewer ListUrlBuilder style)
        if advance:
            params["advsearch"] = "1"
            if adv_search & 0x1:
                params["f_sname"] = "on"
            if adv_search & 0x2:
                params["f_stags"] = "on"
            if adv_search & 0x4:
                params["f_sdesc"] = "on"
            if adv_search & 0x8:
                params["f_storr"] = "on"
            if adv_search & 0x10:
                params["f_sto"] = "on"
            if adv_search & 0x20:
                params["f_sdt1"] = "on"
            if adv_search & 0x40:
                params["f_sdt2"] = "on"
            if adv_search & 0x80:
                params["f_sh"] = "on"
            if adv_search & 0x100:
                params["f_sfl"] = "on"
            if adv_search & 0x200:
                params["f_sfu"] = "on"
            if adv_search & 0x400:
                params["f_sft"] = "on"
        if min_rating:
            params["f_sr"] = "on"
            params["f_srdd"] = min_rating
        if page_from is not None:
            params["f_sp"] = "on"
            params["f_spf"] = page_from
        if page_to is not None:
            params["f_sp"] = "on"
            params["f_spt"] = page_to

        resp = await self._http.get(f"{self.base_url}/?{urlencode(params)}")
        resp.raise_for_status()
        self._check_auth(resp.text, resp)

        matches = list({(int(g), t) for g, t in _GALLERY_URL_RE.findall(resp.text)})
        total_match = _TOTAL_COUNT_RE.search(resp.text)
        if total_match:
            total = int(total_match.group(1).replace(",", ""))
        else:
            # EH sometimes shows "Showing X results" or no count at all
            # Also try a broader pattern
            alt_match = re.search(r"([\d,]+)\s+result", resp.text)
            total = int(alt_match.group(1).replace(",", "")) if alt_match else len(matches)

        if not matches:
            return {"galleries": [], "total": total, "page": page}

        gid_list = [[gid, tok] for gid, tok in matches]
        galleries = await self._gdata(gid_list)
        return {"galleries": galleries, "total": total, "page": page}

    async def _gdata(self, gid_list: list[list]) -> list[dict]:
        """Batch-fetch gallery metadata via gdata API (max 25 per call)."""
        results: list[dict] = []
        for chunk in _chunks(gid_list, 25):
            resp = await self._api({"method": "gdata", "gidlist": chunk, "namespace": 1})
            for g in resp.get("gmetadata", []):
                if not g.get("error"):
                    results.append(_parse_gmetadata(g))
        return results

    async def get_gallery_metadata(self, gid: int, token: str) -> dict:
        results = await self._gdata([[gid, token]])
        if not results:
            raise ValueError(f"Gallery {gid}/{token} not found or expunged")
        return results[0]

    def _parse_detail_html(self, html: str) -> tuple[dict[int, str], dict[int, str]]:
        """Parse a single gallery detail page HTML for pTokens + preview thumbnails."""
        token_map: dict[int, str] = {}
        preview_map: dict[int, str] = {}

        # Extract pTokens from preview links
        for match in _PTOKEN_RE.finditer(html):
            ptoken = match.group(1)
            page_num = int(match.group(3))
            token_map[page_num] = ptoken

        # Extract preview thumbnails — try new format first (2024+), then legacy formats
        new_matches = list(_NEW_PREVIEW_RE.finditer(html))
        if new_matches:
            # New format: background url() with optional sprite offset
            # Groups: (page_num, width, height, thumb_url, offset_x)
            for match in new_matches:
                page_num = int(match.group(1))
                width = int(match.group(2))
                height = int(match.group(3))
                thumb_url = match.group(4)
                offset_x = int(match.group(5))
                # Always store as sprite format — even offset 0 is part of the sprite sheet
                preview_map[page_num] = f"{thumb_url}|{offset_x}|{width}|{height}"

        else:
            # Legacy large previews: <div class="gdtl"><img alt="N" src="URL">
            large_matches = list(_LARGE_PREVIEW_RE.finditer(html))
            if large_matches:
                for match in large_matches:
                    page_num = int(match.group(1))
                    thumb_url = match.group(2)
                    preview_map[page_num] = thumb_url
            else:
                # Legacy normal previews (CSS sprite sheets with gdtm class)
                # Store as "url|offsetX|width|height" for frontend to render
                for match in _NORMAL_PREVIEW_RE.finditer(html):
                    sprite_url = match.group(1)
                    offset_x = int(match.group(2))
                    width = int(match.group(3))
                    height = int(match.group(4))
                    page_num = int(match.group(5))
                    preview_map[page_num] = f"{sprite_url}|{offset_x}|{width}|{height}"

        return token_map, preview_map

    async def get_previews(self, gid: int, token: str) -> dict[int, str]:
        """
        Fetch ONLY the first gallery detail page (p=0) to extract
        ~20 preview thumbnail URLs.  Very fast — single HTTP request.
        Used for the gallery detail/info page before the user reads.
        """
        url = f"{self.base_url}/g/{gid}/{token}/?p=0"
        resp = await self._http.get(url)
        resp.raise_for_status()
        self._check_auth(resp.text, resp)

        _, preview_map = self._parse_detail_html(resp.text)
        return preview_map

    async def get_image_tokens(self, gid: int, token: str, total_pages: int) -> tuple[dict[int, str], dict[int, str]]:
        """
        Get image page tokens (pTokens) and preview thumbnail URLs by
        scraping gallery detail pages.  Matches EhViewer's approach.

        Returns (token_map, preview_map):
          token_map:   {page_num: ptoken}
          preview_map: {page_num: thumbnail_url}
        """
        import asyncio

        token_map: dict[int, str] = {}
        preview_map: dict[int, str] = {}
        pages_per_detail = 20  # EH shows ~20 previews per detail page

        detail_pages = (total_pages + pages_per_detail - 1) // pages_per_detail
        for dp in range(detail_pages):
            if dp > 0:
                await asyncio.sleep(0.3)

            url = f"{self.base_url}/g/{gid}/{token}/?p={dp}"
            resp = await self._http.get(url)
            resp.raise_for_status()
            self._check_auth(resp.text, resp)

            page_tokens, page_previews = self._parse_detail_html(resp.text)
            token_map.update(page_tokens)
            preview_map.update(page_previews)

        return token_map, preview_map

    async def get_image_tokens_paginated(
        self,
        gid: int,
        token: str,
        total_pages: int,
        start_page: int = 0,
        count: int = 20,
    ) -> dict:
        """
        Fetch image pTokens and preview thumbnails for a single window of pages.

        EH detail pages show 20 thumbnails each (p=0 has pages 1-20,
        p=1 has pages 21-40, etc.).  This method maps ``start_page``
        (0-based image index) to the minimal set of EH detail pages
        needed to satisfy ``count`` images and performs only those
        HTTP requests.

        Args:
            gid:         Gallery numeric ID.
            token:       Gallery token string.
            total_pages: Total image count (used to compute ``has_more``
                         and to clamp out-of-range requests).
            start_page:  0-based image index of the first image wanted.
            count:       Number of images to return (1-100).

        Returns:
            {
                "images":   [{"page": int, "token": str}, ...],
                "previews": {"<page>": "<thumb_url|sprite>", ...},
                "has_more": bool,
                "total":    int,
            }
        """
        import asyncio

        THUMBS_PER_DETAIL = 20  # EH always shows 20 thumbnails per detail page

        # Clamp start_page to valid range.
        if total_pages == 0 or start_page >= total_pages:
            return {"images": [], "previews": {}, "has_more": False, "total": total_pages}

        end_page_excl = min(start_page + count, total_pages)  # exclusive upper bound

        # Detail page numbers (0-based) that cover [start_page, end_page_excl).
        first_dp = start_page // THUMBS_PER_DETAIL
        last_dp = (end_page_excl - 1) // THUMBS_PER_DETAIL

        token_map: dict[int, str] = {}
        preview_map: dict[int, str] = {}

        for dp in range(first_dp, last_dp + 1):
            if dp > first_dp:
                await asyncio.sleep(0.3)  # polite delay between requests

            url = f"{self.base_url}/g/{gid}/{token}/?p={dp}"
            resp = await self._http.get(url)
            resp.raise_for_status()
            self._check_auth(resp.text, resp)

            page_tokens, page_previews = self._parse_detail_html(resp.text)
            token_map.update(page_tokens)
            preview_map.update(page_previews)

        # Build ordered list for the requested window (1-based page numbers on EH).
        # EH page numbers in the HTML are 1-based; start_page here is 0-based index.
        images = []
        for img_idx in range(start_page, end_page_excl):
            page_num = img_idx + 1  # EH is 1-based
            pt = token_map.get(page_num)
            if pt:
                images.append({"page": page_num, "token": pt})

        # EH page keys are 1-based; start_page is 0-based.
        str_previews = {str(k): v for k, v in preview_map.items() if start_page + 1 <= k <= end_page_excl}

        return {
            "images": images,
            "previews": str_previews,
            "has_more": end_page_excl < total_pages,
            "total": total_pages,
        }

    async def get_image_url(self, image_page_token: str, gid: int, page: int) -> str:
        """
        Fetch the image page HTML and extract the actual image URL.
        Page URL: /s/{image_page_token}/{gid}-{page}
        """
        url = f"{self.base_url}/s/{image_page_token}/{gid}-{page}"
        resp = await self._http.get(url)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "lxml")
        img_tag = soup.find("img", id="img")
        if not img_tag or not img_tag.get("src"):
            raise ValueError(f"Image src not found for {gid}-{page}")
        return img_tag["src"]

    async def get_showkey(self, gid: int, page: int, image_page_token: str) -> tuple[str, str | None]:
        """Fetch image page HTML, extract showkey + nl param.
        GET /s/{image_page_token}/{gid}-{page}
        Returns (showkey, nl_param_or_None)
        """
        url = f"{self.base_url}/s/{image_page_token}/{gid}-{page}"
        resp = await self._http.get(url)
        resp.raise_for_status()
        self._check_auth(resp.text, resp)

        m = _SHOWKEY_RE.search(resp.text)
        if not m:
            raise ValueError(f"showkey not found for {gid}-{page}")
        showkey = m.group(1)

        nl_m = _NL_RE.search(resp.text)
        nl_param = nl_m.group(1) if nl_m else None

        return showkey, nl_param

    async def get_image_url_via_api(self, showkey: str, gid: int, page: int, imgkey: str, nl: str = "") -> tuple[str, str | None]:
        """Use showpage JSON API for fast image URL resolution.
        POST to api.php with method=showpage.
        Response JSON has:
          - i3: HTML containing <img id="img" src="IMAGE_URL">
          - i6: HTML containing onclick="return nl('NL_PARAM')"
        Returns (image_url, nl_param)
        """
        payload: dict = {
            "method": "showpage",
            "gid": gid,
            "page": page,
            "imgkey": imgkey,
            "showkey": showkey,
        }
        if nl:
            payload["nl"] = nl

        api_url = f"{self.base_url}/api.php" if self.base_url == EX_BASE_URL else EH_API_URL
        resp = await self._http.post(api_url, json=payload)
        resp.raise_for_status()
        data = resp.json()

        if data.get("error"):
            raise ValueError(f"showpage API error: {data['error']}")

        # Parse image URL from i3 field (HTML string containing img tag)
        i3 = data.get("i3", "")
        img_match = re.search(r'<img[^>]+src="([^"]+)"', i3)
        if not img_match:
            raise ValueError(f"Image URL not found in showpage response for {gid}-{page}")
        image_url = img_match.group(1)

        # Parse nl param from i6 field
        i6 = data.get("i6", "")
        nl_match = _NL_RE.search(i6)
        nl_param = nl_match.group(1) if nl_match else None

        return image_url, nl_param

    async def download_image_with_retry(self, showkey: str, gid: int, page: int, imgkey: str, max_retries: int = 3) -> tuple[bytes, str, str]:
        """Resolve URL via showpage API + download with nl retry on stall/error.
        Returns (image_bytes, media_type, filename_ext)
        """
        nl = ""
        nl_param: str | None = None
        last_error: Exception | None = None

        for attempt in range(max_retries):
            try:
                image_url, nl_param = await self.get_image_url_via_api(showkey, gid, page, imgkey, nl=nl)

                # Download the image (use _img_http with follow_redirects=True for H@H)
                resp = await self._img_http.get(image_url)
                resp.raise_for_status()
                image_data = resp.content

                if len(image_data) < 100:
                    # Suspiciously small — might be an error page
                    raise ValueError(f"Image too small ({len(image_data)} bytes), possible error")

                media_type = _detect_media_type(image_data)
                ext_map = {"image/jpeg": "jpg", "image/png": "png", "image/gif": "gif", "image/webp": "webp"}
                ext = ext_map.get(media_type, "jpg")

                return image_data, media_type, ext

            except (httpx.TimeoutException, httpx.HTTPStatusError, ValueError) as exc:
                last_error = exc
                logger.warning("[eh_download] page %d attempt %d failed: %s", page, attempt + 1, exc)
                # Use nl param to try a different H@H server
                if nl_param:
                    nl = nl_param

        raise RuntimeError(f"Failed to download page {page} after {max_retries} attempts: {last_error}")

    async def fetch_image_bytes(self, image_url: str) -> tuple[bytes, str]:
        """Fetch image bytes. Returns (bytes, media_type)."""
        resp = await self._http.get(image_url)
        resp.raise_for_status()
        data = resp.content
        return data, _detect_media_type(data)

    async def get_favorites(
        self,
        favcat: int | str = "all",
        search: str = "",
        next_cursor: str = "",
        prev_cursor: str = "",
    ) -> dict:
        """
        Scrape E-H favorites page using cursor-based pagination.
        EH favorites uses `next={gid}-{timestamp}` / `prev={gid}-{timestamp}` params,
        NOT page numbers (page=N only works for 0 and 1).

        Returns: {"galleries": [...], "total": N, "has_next": bool, "has_prev": bool,
                  "next_cursor": str|null, "prev_cursor": str|null,
                  "categories": [{name, count, index}]}
        """
        params: dict[str, Any] = {}
        if favcat != "all":
            params["favcat"] = int(favcat)
        if search:
            params["f_search"] = search
        if next_cursor:
            params["next"] = next_cursor
        elif prev_cursor:
            params["prev"] = prev_cursor

        resp = await self._http.get(f"{self.base_url}/favorites.php?{urlencode(params)}")
        resp.raise_for_status()
        self._check_auth(resp.text, resp)

        # Parse gallery links
        matches = list({(int(g), t) for g, t in _GALLERY_URL_RE.findall(resp.text)})

        soup = BeautifulSoup(resp.text, "lxml")

        # Parse next/prev cursors from #unext and #uprev elements
        # When enabled: <a id="unext" href="...?next=GID">; disabled: <span id="unext">
        has_next = False
        has_prev = False
        out_next_cursor: str | None = None
        out_prev_cursor: str | None = None

        unext = soup.find(id="unext")
        if unext and unext.name == "a":
            has_next = True
            href = unext.get("href", "")
            m = re.search(r"[?&]next=([^&]+)", href)
            if m:
                out_next_cursor = m.group(1)

        uprev = soup.find(id="uprev")
        if uprev and uprev.name == "a":
            has_prev = True
            href = uprev.get("href", "")
            m = re.search(r"[?&]prev=([^&]+)", href)
            if m:
                out_prev_cursor = m.group(1)

        # Parse favorite category names and counts from sidebar (.fp divs)
        # Structure: <div class="fp" onclick="document.location='...?favcat=N'">
        #   <div>COUNT</div>
        #   <div class="i" title="Category Name">...</div>
        # </div>
        categories: list[dict] = []
        for div in soup.select(".fp"):
            onclick = div.get("onclick", "")
            idx_match = re.search(r"favcat=(\d+)", onclick)
            if not idx_match:
                continue
            idx = int(idx_match.group(1))
            # Count is the first numeric text
            count = 0
            for text in div.stripped_strings:
                if text.isdigit():
                    count = int(text)
                    break
            # Name from .i div title attribute, fallback to last text
            i_div = div.find(class_="i")
            name = ""
            if i_div and i_div.get("title"):
                name = i_div["title"]
            else:
                texts = list(div.stripped_strings)
                name = texts[-1] if len(texts) > 1 else f"Favorites {idx}"
            categories.append({"index": idx, "name": name, "count": count})

        # Compute total from category counts (more reliable than regex on favorites page)
        if categories:
            if favcat == "all":
                total = sum(c["count"] for c in categories)
            else:
                cat_idx = int(favcat)
                cat = next((c for c in categories if c["index"] == cat_idx), None)
                total = cat["count"] if cat else len(matches)
        else:
            total = len(matches)

        # Fallback: if parsing found nothing, provide default 0-9 categories
        if not categories:
            _DEFAULT_FAV_NAMES = [
                "Favorites 0",
                "Favorites 1",
                "Favorites 2",
                "Favorites 3",
                "Favorites 4",
                "Favorites 5",
                "Favorites 6",
                "Favorites 7",
                "Favorites 8",
                "Favorites 9",
            ]
            for i in range(10):
                categories.append({"index": i, "name": _DEFAULT_FAV_NAMES[i], "count": 0})

        galleries: list[dict] = []
        if matches:
            gid_list = [[gid, tok] for gid, tok in matches]
            galleries = await self._gdata(gid_list)

        return {
            "galleries": galleries,
            "total": total,
            "has_next": has_next,
            "has_prev": has_prev,
            "next_cursor": out_next_cursor,
            "prev_cursor": out_prev_cursor,
            "categories": categories,
        }

    async def add_favorite(self, gid: int, token: str, favcat: int = 0, note: str = "") -> bool:
        """Add gallery to cloud favorites. favcat: 0-9, note: max 250 chars."""
        url = f"{self.base_url}/gallerypopups.php?gid={gid}&t={token}&act=addfav"
        data = {
            "favcat": str(favcat),
            "favnote": note[:250],
            "submit": "Apply Changes",
            "update": "1",
        }
        resp = await self._http.post(
            url,
            data=data,
            headers={
                "Referer": url,
                "Origin": self.base_url,
            },
        )
        resp.raise_for_status()
        return True

    async def remove_favorite(self, gid: int, token: str) -> bool:
        """Remove gallery from cloud favorites."""
        url = f"{self.base_url}/gallerypopups.php?gid={gid}&t={token}&act=addfav"
        data = {
            "favcat": "favdel",
            "favnote": "",
            "submit": "Apply Changes",
            "update": "1",
        }
        resp = await self._http.post(
            url,
            data=data,
            headers={
                "Referer": url,
                "Origin": self.base_url,
            },
        )
        resp.raise_for_status()
        return True

    async def get_popular(self) -> dict:
        """
        Scrape E-H popular page and return galleries.
        GET {base_url}/popular
        """
        resp = await self._http.get(f"{self.base_url}/popular")
        resp.raise_for_status()
        self._check_auth(resp.text, resp)

        matches = list({(int(g), t) for g, t in _GALLERY_URL_RE.findall(resp.text)})
        if not matches:
            return {"galleries": []}

        gid_list = [[gid, tok] for gid, tok in matches]
        galleries = await self._gdata(gid_list)
        return {"galleries": galleries}

    async def get_toplist(self, tl: int, page: int = 0) -> dict:
        """
        Scrape E-H top list page.
        GET {base_url}/toplist.php?tl={tl}&p={page}
        tl: 11=All-Time, 12=Past Year, 13=Past Month, 14=Yesterday, 15=Past Hour
        """
        resp = await self._http.get(f"{self.base_url}/toplist.php?tl={tl}&p={page}")
        resp.raise_for_status()
        self._check_auth(resp.text, resp)

        matches = list({(int(g), t) for g, t in _GALLERY_URL_RE.findall(resp.text)})
        total_match = _TOTAL_COUNT_RE.search(resp.text)
        total = int(total_match.group(1).replace(",", "")) if total_match else len(matches)

        if not matches:
            return {"galleries": [], "total": total, "page": page}

        gid_list = [[gid, tok] for gid, tok in matches]
        galleries = await self._gdata(gid_list)
        return {"galleries": galleries, "total": total, "page": page}

    async def get_comments(self, gid: int, token: str) -> list[dict]:
        """
        Scrape gallery comments from gallery detail page.
        Returns list of {poster, posted_at, text, score}.
        """
        url = f"{self.base_url}/g/{gid}/{token}/?p=0"
        resp = await self._http.get(url)
        resp.raise_for_status()
        self._check_auth(resp.text, resp)

        soup = BeautifulSoup(resp.text, "lxml")
        comments: list[dict] = []

        for c1 in soup.select("div.c1"):
            c3 = c1.find("div", class_="c3")
            c6 = c1.find("div", class_="c6")
            c5 = c1.find("div", class_="c5")

            poster = ""
            posted_at = ""
            if c3:
                c3_text = c3.get_text(" ", strip=True)
                # "Posted on {date} UTC by: {poster}"
                by_match = re.search(r"by:\s*(.+)$", c3_text)
                if by_match:
                    poster = by_match.group(1).strip()
                date_match = re.search(r"Posted on\s+(.+?)\s+UTC", c3_text)
                if date_match:
                    posted_at = date_match.group(1).strip()

            text = c6.decode_contents().strip() if c6 else ""
            score_text = c5.get_text(strip=True) if c5 else ""
            score: int | None = None
            if score_text:
                score_match = re.search(r"([+-]?\d+)", score_text)
                if score_match:
                    score = int(score_match.group(1))

            comments.append({
                "poster": poster,
                "posted_at": posted_at,
                "text": text,
                "score": score,
            })

        return comments

    async def check_cookies(self) -> bool:
        """Verify that the current cookies give authenticated access."""
        try:
            resp = await self._http.get(f"{self.base_url}/home.php")
            return "Credits" in resp.text or "Hath" in resp.text
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            logger.warning("check_cookies request failed: %s", exc)
            return False

    async def get_account_info(self) -> dict:
        """Parse GP credits and Hath status from home.php."""
        try:
            resp = await self._http.get(f"{self.base_url}/home.php")
            info: dict[str, Any] = {}
            m = re.search(r"([\d,]+)\s+Credits", resp.text)
            if m:
                info["credits"] = int(m.group(1).replace(",", ""))
            m = re.search(r"Hath\s+Perks.*?(\d+)", resp.text, re.DOTALL)
            if m:
                info["hath_perks"] = int(m.group(1))
            return info
        except (httpx.HTTPError, httpx.TimeoutException, AttributeError, ValueError) as exc:
            logger.error("get_account_info failed: %s", exc)
            return {"error": str(exc)}
