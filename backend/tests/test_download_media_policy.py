"""Tests for the generic download media policy (``options.media``).

Covers ``services.download_policy`` (MediaPolicy model + option normalization)
and the plugin-registry capability ``supports_media_policy`` that decides
whether the plugin handling a URL honours the policy.
"""

from unittest.mock import AsyncMock, patch

import pytest

from services.download_policy import (
    MediaPolicy,
    media_policy_from_options,
    normalize_download_options,
)

_TWITTER_URL = "https://x.com/someuser"
# The EH gallery token must be 10 hex chars or the native plugin does not claim the URL.
_EH_GALLERY_URL = "https://e-hentai.org/g/123456/abcdef1234/"
_PATCH_SUPPORTS = "plugins.registry.plugin_registry.supports_media_policy"


# ---------------------------------------------------------------------------
# MediaPolicy / media_policy_from_options
# ---------------------------------------------------------------------------


def test_media_policy_is_default_true_for_empty_policy():
    assert MediaPolicy().is_default is True


def test_media_policy_is_default_false_when_videos_excluded():
    assert MediaPolicy(include_videos=False).is_default is False


def test_media_policy_is_default_false_when_max_files_set():
    assert MediaPolicy(max_files=20).is_default is False


def test_media_policy_from_options_returns_none_when_media_key_absent():
    assert media_policy_from_options({}) is None
    assert media_policy_from_options(None) is None


def test_media_policy_from_options_returns_none_for_default_policy():
    assert media_policy_from_options({"media": {"max_files": None, "include_videos": True}}) is None


def test_media_policy_from_options_returns_policy_for_non_default():
    policy = media_policy_from_options({"media": {"max_files": 200, "include_videos": False}})
    assert policy == MediaPolicy(max_files=200, include_videos=False)


def test_media_policy_rejects_zero_max_files():
    with pytest.raises(ValueError):
        media_policy_from_options({"media": {"max_files": 0}})


def test_media_policy_rejects_max_files_above_limit():
    with pytest.raises(ValueError):
        media_policy_from_options({"media": {"max_files": 100_001}})


def test_media_policy_accepts_max_files_at_upper_limit():
    policy = media_policy_from_options({"media": {"max_files": 100_000}})
    assert policy is not None and policy.max_files == 100_000


def test_media_policy_rejects_negative_max_files():
    with pytest.raises(ValueError):
        media_policy_from_options({"media": {"max_files": -5}})


def test_media_policy_rejects_unknown_key():
    with pytest.raises(ValueError):
        media_policy_from_options({"media": {"max_files": 10, "include_gifs": False}})


def test_media_policy_rejects_non_object_media_value():
    with pytest.raises(ValueError):
        media_policy_from_options({"media": "all"})


# ---------------------------------------------------------------------------
# normalize_download_options
# ---------------------------------------------------------------------------


async def test_media_policy_default_is_dropped_from_options():
    """A default policy is never persisted: absent key == today's behaviour."""
    with patch(_PATCH_SUPPORTS, new_callable=AsyncMock, return_value=True) as supports:
        result = await normalize_download_options(_TWITTER_URL, "twitter", {"media": {"include_videos": True}})

    assert result is not None
    assert "media" not in result
    # Dropping a default must not depend on the capability lookup.
    supports.assert_not_awaited()


async def test_media_policy_default_dropped_keeps_other_option_keys():
    with patch(_PATCH_SUPPORTS, new_callable=AsyncMock, return_value=False):
        result = await normalize_download_options(
            _EH_GALLERY_URL, "ehentai", {"media": {"max_files": None, "include_videos": True}, "x": 1}
        )

    assert result == {"x": 1}


async def test_media_policy_none_options_returns_none():
    assert await normalize_download_options(_TWITTER_URL, "twitter", None) is None


async def test_media_policy_absent_key_leaves_options_untouched():
    result = await normalize_download_options(_TWITTER_URL, "twitter", {"filesize_min": "100k"})
    assert result == {"filesize_min": "100k"}


async def test_media_policy_rejected_for_native_handler_url():
    """A non-default policy on a URL a native plugin handles must be refused."""
    with patch(_PATCH_SUPPORTS, new_callable=AsyncMock, return_value=False):
        with pytest.raises(ValueError, match="media options are not supported for this source"):
            await normalize_download_options(_EH_GALLERY_URL, "ehentai", {"media": {"max_files": 5}})


async def test_media_policy_kept_for_gallery_dl_url():
    with patch(_PATCH_SUPPORTS, new_callable=AsyncMock, return_value=True):
        result = await normalize_download_options(
            _TWITTER_URL, "twitter", {"media": {"max_files": 200, "include_videos": False}}
        )

    assert result == {"media": {"max_files": 200, "include_videos": False}}


async def test_media_policy_partial_input_is_canonicalized_with_defaults():
    """Only the changed field is sent; the stored shape is the full canonical dict."""
    with patch(_PATCH_SUPPORTS, new_callable=AsyncMock, return_value=True):
        result = await normalize_download_options(_TWITTER_URL, "twitter", {"media": {"max_files": 50}})

    assert result == {"media": {"max_files": 50, "include_videos": True}}


async def test_media_policy_invalid_value_raises_before_capability_check():
    with patch(_PATCH_SUPPORTS, new_callable=AsyncMock, return_value=True):
        with pytest.raises(ValueError):
            await normalize_download_options(_TWITTER_URL, "twitter", {"media": {"max_files": 0}})


async def test_media_policy_normalization_does_not_mutate_caller_options():
    original = {"media": {"max_files": 3}, "other": True}
    with patch(_PATCH_SUPPORTS, new_callable=AsyncMock, return_value=True):
        await normalize_download_options(_TWITTER_URL, "twitter", original)

    assert original == {"media": {"max_files": 3}, "other": True}


async def test_fanbox_options_still_normalized_alongside_media():
    """Fanbox canonicalization must still run when a media key is also present."""
    with patch(_PATCH_SUPPORTS, new_callable=AsyncMock, return_value=True):
        result = await normalize_download_options(
            "https://creator.fanbox.cc/",
            "fanbox",
            {"fanbox": {"content": "free_only"}, "media": {"max_files": 10}},
        )

    assert result is not None
    # Canonical fanbox policy has every field filled in, not just the one sent.
    assert result["fanbox"]["content"] == "free_only"
    assert result["fanbox"]["include_files"] is False
    assert result["fanbox"]["include_images"] is True
    assert result["media"] == {"max_files": 10, "include_videos": True}


async def test_fanbox_options_normalized_and_default_media_dropped():
    with patch(_PATCH_SUPPORTS, new_callable=AsyncMock, return_value=False):
        result = await normalize_download_options(
            "https://creator.fanbox.cc/",
            "fanbox",
            {"fanbox": {"content": "free_only"}, "media": {"include_videos": True}},
        )

    assert result is not None
    assert "media" not in result
    assert result["fanbox"]["content"] == "free_only"
    assert "include_files" in result["fanbox"]


# ---------------------------------------------------------------------------
# Plugin capability: PluginRegistry.supports_media_policy (real registry)
# ---------------------------------------------------------------------------


def test_source_plugin_base_does_not_support_media_policy():
    from plugins.base import SourcePlugin

    assert SourcePlugin.supports_media_policy is False


def test_gallery_dl_plugin_declares_media_policy_support():
    from plugins.builtin.gallery_dl.source import GalleryDlPlugin

    assert GalleryDlPlugin.supports_media_policy is True


async def test_supports_media_policy_true_for_twitter_url():
    """Twitter has no native plugin, so the gallery-dl fallback handles it."""
    from plugins.registry import plugin_registry

    assert await plugin_registry.supports_media_policy("https://x.com/someuser") is True
    assert await plugin_registry.supports_media_policy("https://twitter.com/someuser/media") is True


async def test_supports_media_policy_false_for_eh_gallery_url():
    from plugins.registry import plugin_registry

    assert await plugin_registry.supports_media_policy(_EH_GALLERY_URL) is False


async def test_supports_media_policy_false_for_pixiv_url():
    from plugins.registry import plugin_registry

    assert await plugin_registry.supports_media_policy("https://www.pixiv.net/artworks/12345") is False


async def test_supports_media_policy_true_for_eh_tag_search_url():
    """EH URLs the native plugin does not claim fall through to gallery-dl."""
    from plugins.registry import plugin_registry

    assert await plugin_registry.supports_media_policy("https://e-hentai.org/?f_search=artist%3Asomeone") is True


async def test_supports_media_policy_false_when_no_handler_and_no_fallback():
    """With neither a native handler nor a fallback the answer is False, not an error."""
    from plugins.registry import PluginRegistry

    registry = PluginRegistry()
    assert await registry.supports_media_policy("https://example.com/x") is False
