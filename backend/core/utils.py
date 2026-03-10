"""Shared utility functions used across routers and workers."""


def detect_source(url: str) -> str:
    """Auto-detect download source from URL domain."""
    if "pixiv.net" in url:
        return "pixiv"
    if "e-hentai.org" in url or "exhentai.org" in url:
        return "ehentai"
    if "twitter.com" in url or "x.com" in url:
        return "twitter"
    return "unknown"
