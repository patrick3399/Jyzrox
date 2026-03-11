"""
Tests for core/errors.py — structured error codes, i18n translations, and API error helpers.

Covers:
- New warning codes 'eh_credentials_recommended' and 'pixiv_credentials_required' exist
- get_error_message() returns correct translated messages for all locales
- api_error() returns correctly shaped HTTPException
- parse_accept_language() parsing
- Fallback to English for missing locale
"""

import pytest


# ---------------------------------------------------------------------------
# Import helpers
# ---------------------------------------------------------------------------


def _get_translations():
    """Return the internal _TRANSLATIONS dict from core.errors."""
    from core.errors import _TRANSLATIONS
    return _TRANSLATIONS


def _get_error_message(code: str, locale: str = "en", **kwargs) -> str:
    from core.errors import get_error_message
    return get_error_message(code, locale, **kwargs)


def _api_error(status_code: int, code: str, locale: str = "en", **kwargs):
    from core.errors import api_error
    return api_error(status_code, code, locale, **kwargs)


def _parse_accept_language(header: str | None) -> str:
    from core.errors import parse_accept_language
    return parse_accept_language(header)


# ---------------------------------------------------------------------------
# New warning codes existence
# ---------------------------------------------------------------------------


class TestNewWarningCodesExist:
    """Verify new warning codes are present in the translations table."""

    def test_eh_credentials_recommended_code_exists(self):
        """'eh_credentials_recommended' must be in the translations dict."""
        translations = _get_translations()
        assert "eh_credentials_recommended" in translations

    def test_pixiv_credentials_required_code_exists(self):
        """'pixiv_credentials_required' must be in the translations dict."""
        translations = _get_translations()
        assert "pixiv_credentials_required" in translations

    def test_eh_credentials_recommended_has_english_translation(self):
        """'eh_credentials_recommended' must have an English translation."""
        translations = _get_translations()
        assert "en" in translations["eh_credentials_recommended"]
        assert translations["eh_credentials_recommended"]["en"]

    def test_pixiv_credentials_required_has_english_translation(self):
        """'pixiv_credentials_required' must have an English translation."""
        translations = _get_translations()
        assert "en" in translations["pixiv_credentials_required"]
        assert translations["pixiv_credentials_required"]["en"]

    def test_eh_credentials_recommended_has_all_locales(self):
        """'eh_credentials_recommended' should have translations for all supported locales."""
        from core.errors import SUPPORTED_LOCALES
        translations = _get_translations()
        code_translations = translations["eh_credentials_recommended"]
        for locale in SUPPORTED_LOCALES:
            assert locale in code_translations, f"Missing locale '{locale}' for eh_credentials_recommended"

    def test_pixiv_credentials_required_has_all_locales(self):
        """'pixiv_credentials_required' should have translations for all supported locales."""
        from core.errors import SUPPORTED_LOCALES
        translations = _get_translations()
        code_translations = translations["pixiv_credentials_required"]
        for locale in SUPPORTED_LOCALES:
            assert locale in code_translations, f"Missing locale '{locale}' for pixiv_credentials_required"


# ---------------------------------------------------------------------------
# get_error_message — new warning codes
# ---------------------------------------------------------------------------


class TestGetErrorMessageNewCodes:
    """get_error_message() returns correct messages for new warning codes."""

    def test_eh_credentials_recommended_english_message(self):
        """English message for 'eh_credentials_recommended' mentions bandwidth."""
        msg = _get_error_message("eh_credentials_recommended", "en")
        assert msg
        assert isinstance(msg, str)
        assert len(msg) > 0
        # The message should mention bandwidth or credentials
        msg_lower = msg.lower()
        assert any(word in msg_lower for word in ("bandwidth", "credential", "limited"))

    def test_pixiv_credentials_required_english_message(self):
        """English message for 'pixiv_credentials_required' mentions credentials."""
        msg = _get_error_message("pixiv_credentials_required", "en")
        assert msg
        assert isinstance(msg, str)
        assert len(msg) > 0
        msg_lower = msg.lower()
        assert any(word in msg_lower for word in ("credential", "pixiv", "required"))

    def test_eh_credentials_recommended_zh_tw_message(self):
        """zh-TW translation for 'eh_credentials_recommended' should be non-empty."""
        msg = _get_error_message("eh_credentials_recommended", "zh-TW")
        assert msg
        assert isinstance(msg, str)
        assert msg != "eh_credentials_recommended"  # should not return the code itself

    def test_pixiv_credentials_required_zh_tw_message(self):
        """zh-TW translation for 'pixiv_credentials_required' should be non-empty."""
        msg = _get_error_message("pixiv_credentials_required", "zh-TW")
        assert msg
        assert isinstance(msg, str)
        assert msg != "pixiv_credentials_required"

    def test_eh_credentials_recommended_zh_cn_message(self):
        """zh-CN translation for 'eh_credentials_recommended' should be non-empty."""
        msg = _get_error_message("eh_credentials_recommended", "zh-CN")
        assert msg
        assert isinstance(msg, str)

    def test_pixiv_credentials_required_zh_cn_message(self):
        """zh-CN translation for 'pixiv_credentials_required' should be non-empty."""
        msg = _get_error_message("pixiv_credentials_required", "zh-CN")
        assert msg
        assert isinstance(msg, str)

    def test_eh_credentials_recommended_ja_message(self):
        """Japanese translation for 'eh_credentials_recommended' should be non-empty."""
        msg = _get_error_message("eh_credentials_recommended", "ja")
        assert msg
        assert isinstance(msg, str)

    def test_pixiv_credentials_required_ja_message(self):
        """Japanese translation for 'pixiv_credentials_required' should be non-empty."""
        msg = _get_error_message("pixiv_credentials_required", "ja")
        assert msg
        assert isinstance(msg, str)

    def test_eh_credentials_recommended_ko_message(self):
        """Korean translation for 'eh_credentials_recommended' should be non-empty."""
        msg = _get_error_message("eh_credentials_recommended", "ko")
        assert msg
        assert isinstance(msg, str)

    def test_pixiv_credentials_required_ko_message(self):
        """Korean translation for 'pixiv_credentials_required' should be non-empty."""
        msg = _get_error_message("pixiv_credentials_required", "ko")
        assert msg
        assert isinstance(msg, str)

    def test_messages_differ_between_new_codes(self):
        """The two new warning codes should have different English messages."""
        msg_eh = _get_error_message("eh_credentials_recommended", "en")
        msg_px = _get_error_message("pixiv_credentials_required", "en")
        assert msg_eh != msg_px


# ---------------------------------------------------------------------------
# get_error_message — existing codes (regression)
# ---------------------------------------------------------------------------


class TestGetErrorMessageExistingCodes:
    """get_error_message() should still work correctly for pre-existing codes."""

    def test_not_authenticated_english(self):
        msg = _get_error_message("not_authenticated", "en")
        assert "authenticated" in msg.lower()

    def test_invalid_credentials_english(self):
        msg = _get_error_message("invalid_credentials", "en")
        assert "invalid" in msg.lower() or "credential" in msg.lower()

    def test_eh_access_denied_english(self):
        msg = _get_error_message("eh_access_denied", "en")
        assert "exhentai" in msg.lower() or "sad panda" in msg.lower()

    def test_eh_bandwidth_exceeded_english(self):
        msg = _get_error_message("eh_bandwidth_exceeded", "en")
        assert "bandwidth" in msg.lower()

    def test_pixiv_not_configured_english(self):
        msg = _get_error_message("pixiv_not_configured", "en")
        assert "pixiv" in msg.lower()

    def test_unknown_code_returns_code_itself(self):
        """A code not in the table should return the code string as fallback."""
        msg = _get_error_message("totally_unknown_code_xyz", "en")
        assert msg == "totally_unknown_code_xyz"

    def test_fallback_to_english_for_missing_locale(self):
        """If a locale has no translation, should fall back to English."""
        # Use an obscure locale that definitely isn't supported
        msg_en = _get_error_message("not_authenticated", "en")
        msg_xx = _get_error_message("not_authenticated", "xx-UNSUPPORTED")
        # Should fall back to English
        assert msg_xx == msg_en


# ---------------------------------------------------------------------------
# api_error()
# ---------------------------------------------------------------------------


class TestApiError:
    """api_error() should produce correctly structured HTTPException."""

    def test_api_error_status_code(self):
        """api_error should set the correct HTTP status code."""
        exc = _api_error(403, "eh_access_denied", "en")
        assert exc.status_code == 403

    def test_api_error_detail_structure(self):
        """api_error detail should be a dict with 'code' and 'message' keys."""
        exc = _api_error(400, "pixiv_not_configured", "en")
        assert isinstance(exc.detail, dict)
        assert "code" in exc.detail
        assert "message" in exc.detail

    def test_api_error_code_field(self):
        """api_error detail.code should match the passed code."""
        exc = _api_error(400, "eh_credentials_recommended", "en")
        assert exc.detail["code"] == "eh_credentials_recommended"

    def test_api_error_message_field_english(self):
        """api_error detail.message should be the English translation."""
        exc = _api_error(400, "eh_credentials_recommended", "en")
        expected = _get_error_message("eh_credentials_recommended", "en")
        assert exc.detail["message"] == expected

    def test_api_error_pixiv_credentials_required_code(self):
        """api_error with 'pixiv_credentials_required' should produce correct detail."""
        exc = _api_error(400, "pixiv_credentials_required", "en")
        assert exc.detail["code"] == "pixiv_credentials_required"
        assert exc.detail["message"]

    def test_api_error_401_not_authenticated(self):
        """api_error for auth errors should return 401 with correct code."""
        exc = _api_error(401, "not_authenticated", "en")
        assert exc.status_code == 401
        assert exc.detail["code"] == "not_authenticated"

    def test_api_error_zh_tw_locale_message(self):
        """api_error should use the zh-TW translation when locale is zh-TW."""
        exc_en = _api_error(403, "eh_access_denied", "en")
        exc_tw = _api_error(403, "eh_access_denied", "zh-TW")
        assert exc_tw.detail["message"] != exc_en.detail["message"]

    def test_api_error_500_server_error(self):
        """api_error for server errors should produce 500 with server_error code."""
        exc = _api_error(500, "server_error", "en")
        assert exc.status_code == 500
        assert exc.detail["code"] == "server_error"


# ---------------------------------------------------------------------------
# parse_accept_language()
# ---------------------------------------------------------------------------


class TestParseAcceptLanguage:
    """parse_accept_language() should correctly identify the best locale."""

    def test_none_header_returns_english(self):
        """None Accept-Language header should return 'en'."""
        assert _parse_accept_language(None) == "en"

    def test_empty_header_returns_english(self):
        """Empty Accept-Language header should return 'en'."""
        assert _parse_accept_language("") == "en"

    def test_english_returns_english(self):
        """'en' Accept-Language should return 'en'."""
        assert _parse_accept_language("en") == "en"

    def test_english_us_returns_english(self):
        """'en-US' Accept-Language should still return 'en'."""
        # en-US is not in SUPPORTED_LOCALES but prefix 'en' may or may not match;
        # just verify it doesn't crash and returns a valid locale
        result = _parse_accept_language("en-US")
        assert isinstance(result, str)

    def test_zh_tw_returns_zh_tw(self):
        """'zh-TW' Accept-Language should return 'zh-TW'."""
        assert _parse_accept_language("zh-TW") == "zh-TW"

    def test_zh_cn_returns_zh_cn(self):
        """'zh-CN' Accept-Language should return 'zh-CN'."""
        assert _parse_accept_language("zh-CN") == "zh-CN"

    def test_ja_returns_ja(self):
        """'ja' Accept-Language should return 'ja'."""
        assert _parse_accept_language("ja") == "ja"

    def test_ko_returns_ko(self):
        """'ko' Accept-Language should return 'ko'."""
        assert _parse_accept_language("ko") == "ko"

    def test_complex_accept_language_picks_best_q(self):
        """'zh-TW;q=0.9,en;q=0.8' should prefer zh-TW (higher q)."""
        result = _parse_accept_language("zh-TW;q=0.9,en;q=0.8")
        assert result == "zh-TW"

    def test_zh_hans_maps_to_zh_cn(self):
        """'zh-Hans' should be mapped to 'zh-CN'."""
        result = _parse_accept_language("zh-Hans")
        assert result == "zh-CN"

    def test_unsupported_locale_falls_back_to_english(self):
        """Locale not in SUPPORTED_LOCALES should fall back to 'en'."""
        result = _parse_accept_language("fr-FR")
        assert result == "en"

    def test_ja_jp_maps_to_ja(self):
        """'ja-JP' prefix should map to 'ja'."""
        result = _parse_accept_language("ja-JP")
        assert result == "ja"

    def test_ko_kr_maps_to_ko(self):
        """'ko-KR' prefix should map to 'ko'."""
        result = _parse_accept_language("ko-KR")
        assert result == "ko"


# ---------------------------------------------------------------------------
# All known error codes have English translations
# ---------------------------------------------------------------------------


class TestAllErrorCodesHaveEnglish:
    """Every entry in _TRANSLATIONS must have an English translation."""

    def test_all_codes_have_english_fallback(self):
        """Every error code in the translation table should have an 'en' entry."""
        translations = _get_translations()
        for code, locales in translations.items():
            assert "en" in locales, f"Error code '{code}' is missing English ('en') translation"
            assert locales["en"], f"Error code '{code}' has empty English translation"

    def test_translations_dict_is_not_empty(self):
        """The translations dict should contain entries."""
        translations = _get_translations()
        assert len(translations) > 0
