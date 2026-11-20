"""Structured API error codes with i18n support."""

import logging

from fastapi import HTTPException

from core.errors_translations_general import TRANSLATIONS_PART_2
from core.errors_translations_sources import TRANSLATIONS_PART_1

logger = logging.getLogger(__name__)

# Error translations: code → {locale → message}
# English is always the fallback
_TRANSLATIONS: dict[str, dict[str, str]] = {**TRANSLATIONS_PART_1, **TRANSLATIONS_PART_2}

SUPPORTED_LOCALES = {"en", "zh-TW", "zh-CN", "ja", "ko"}


def parse_accept_language(header: str | None) -> str:
    """Parse Accept-Language header, return best matching locale."""
    if not header:
        return "en"

    # Parse "en-US,en;q=0.9,zh-TW;q=0.8" format
    best_locale = "en"
    best_q = 0.0

    for part in header.split(","):
        part = part.strip()
        if not part:
            continue

        # Split "lang;q=0.8" or just "lang"
        segments = part.split(";")
        lang = segments[0].strip()
        q = 1.0
        for seg in segments[1:]:
            seg = seg.strip()
            if seg.startswith("q="):
                try:
                    q = float(seg[2:])
                except ValueError:
                    q = 0.0

        # Try exact match first
        if lang in SUPPORTED_LOCALES and q > best_q:
            best_q = q
            best_locale = lang
            continue

        # Try prefix match (e.g., "zh" → "zh-TW", "zh-Hans" → "zh-CN")
        lang_lower = lang.lower()
        if lang_lower.startswith("zh-hans") or lang_lower == "zh-cn":
            if q > best_q and "zh-CN" in SUPPORTED_LOCALES:
                best_q = q
                best_locale = "zh-CN"
        elif lang_lower.startswith("zh"):
            if q > best_q and "zh-TW" in SUPPORTED_LOCALES:
                best_q = q
                best_locale = "zh-TW"
        elif lang_lower.startswith("ja") and q > best_q:
            best_q = q
            best_locale = "ja"
        elif lang_lower.startswith("ko") and q > best_q:
            best_q = q
            best_locale = "ko"

    return best_locale


def get_error_message(code: str, locale: str = "en", **kwargs) -> str:
    """Get translated error message for a code."""
    translations = _TRANSLATIONS.get(code, {})
    msg = translations.get(locale) or translations.get("en", code)
    if kwargs:
        try:
            msg = msg.format(**kwargs)
        except KeyError, IndexError:
            pass
    return msg


def api_error(
    status_code: int,
    code: str,
    locale: str = "en",
    **kwargs,
) -> HTTPException:
    """Create an HTTPException with structured i18n detail."""
    message = get_error_message(code, locale, **kwargs)
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )
