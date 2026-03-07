"""
E-Hentai / ExHentai HTTP client.

References:
  - EhViewer EhEngine.kt
  - https://ehwiki.org/wiki/API
"""

import logging
import re
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
    "misc":        1,
    "doujinshi":   2,
    "manga":       4,
    "artist_cg":   8,
    "game_cg":     16,
    "image_set":   32,
    "cosplay":     64,
    "asian_porn":  128,
    "non_h":       256,
    "western":     512,
}
ALL_CATS = sum(CATEGORY_MASK.values())  # 1023

_GALLERY_URL_RE = re.compile(r"e[x\-]hentai\.org/g/(\d+)/([a-f0-9]{10})/")
_TOTAL_COUNT_RE = re.compile(r"Showing .+? of ([\d,]+)")


def _chunks(lst: list, n: int):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def _parse_gmetadata(g: dict) -> dict:
    """Normalise a single gdata API entry to our internal dict."""
    return {
        "gid":       int(g["gid"]),
        "token":     g["token"],
        "title":     g.get("title", ""),
        "title_jpn": g.get("title_jpn", ""),
        "category":  g.get("category", ""),
        "thumb":     g.get("thumb", ""),
        "uploader":  g.get("uploader", ""),
        "posted_at": int(g.get("posted", 0)),
        "pages":     int(g.get("filecount", 0)),
        "rating":    float(g.get("rating", 0)),
        "tags":      g.get("tags", []),
        "expunged":  bool(g.get("expunged", False)),
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

    async def __aenter__(self) -> "EhClient":
        self._http = httpx.AsyncClient(
            cookies=self.cookies,
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
        return self

    async def __aexit__(self, *_) -> None:
        if self._http:
            await self._http.aclose()

    # ── Internal ─────────────────────────────────────────────────────

    async def _api(self, payload: dict) -> dict:
        resp = await self._http.post(EH_API_URL, json=payload)
        resp.raise_for_status()
        data = resp.json()
        if data.get("error"):
            raise ValueError(f"E-H API error: {data['error']}")
        return data

    def _check_auth(self, html: str) -> None:
        if "You do not have access" in html or (
            "Login" in html[:300] and "ipb_member_id" not in str(self.cookies)
        ):
            raise PermissionError("EH cookie invalid or expired")

    # ── Public API ───────────────────────────────────────────────────

    async def search(
        self,
        query: str = "",
        page: int = 0,
        category: str | None = None,
    ) -> dict:
        """
        Scrape E-H search results.
        Strategy: extract gallery IDs from HTML, then batch via gdata API.
        """
        params: dict[str, Any] = {"page": page}
        if query:
            params["f_search"] = query
        if category and category in CATEGORY_MASK:
            params["f_cats"] = ALL_CATS ^ CATEGORY_MASK[category]

        resp = await self._http.get(f"{self.base_url}/?{urlencode(params)}")
        resp.raise_for_status()
        self._check_auth(resp.text)

        matches = list({(int(g), t) for g, t in _GALLERY_URL_RE.findall(resp.text)})
        total_match = _TOTAL_COUNT_RE.search(resp.text)
        total = int(total_match.group(1).replace(",", "")) if total_match else 0

        if not matches:
            return {"galleries": [], "total": total, "page": page}

        gid_list = [[gid, tok] for gid, tok in matches]
        galleries = await self._gdata(gid_list)
        return {"galleries": galleries, "total": total, "page": page}

    async def _gdata(self, gid_list: list[list]) -> list[dict]:
        """Batch-fetch gallery metadata via gdata API (max 25 per call)."""
        results: list[dict] = []
        for chunk in _chunks(gid_list, 25):
            resp = await self._api(
                {"method": "gdata", "gidlist": chunk, "namespace": 1}
            )
            for g in resp.get("gmetadata", []):
                if not g.get("error"):
                    results.append(_parse_gmetadata(g))
        return results

    async def get_gallery_metadata(self, gid: int, token: str) -> dict:
        results = await self._gdata([[gid, token]])
        if not results:
            raise ValueError(f"Gallery {gid}/{token} not found or expunged")
        return results[0]

    async def get_image_tokens(
        self, gid: int, token: str, total_pages: int
    ) -> dict[int, str]:
        """
        Get image page tokens for all pages via gtoken API.
        Returns {page_num: image_page_token}.
        """
        page_list = [[gid, token, p] for p in range(1, total_pages + 1)]
        token_map: dict[int, str] = {}

        for chunk in _chunks(page_list, 1000):
            resp = await self._api({"method": "gtoken", "pagelist": chunk})
            for i, item in enumerate(resp.get("tokenlist", [])):
                page_num = chunk[i][2]
                token_map[page_num] = item["pt"]

        return token_map

    async def get_image_url(
        self, image_page_token: str, gid: int, page: int
    ) -> str:
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

    async def fetch_image_bytes(self, image_url: str) -> tuple[bytes, str]:
        """Fetch image bytes. Returns (bytes, media_type)."""
        resp = await self._http.get(image_url)
        resp.raise_for_status()
        data = resp.content
        return data, _detect_media_type(data)

    async def check_cookies(self) -> bool:
        """Verify that the current cookies give authenticated access."""
        try:
            resp = await self._http.get(f"{self.base_url}/home.php")
            return "Credits" in resp.text or "Hath" in resp.text
        except Exception:
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
        except Exception as exc:
            return {"error": str(exc)}
