"""Tests for plugin capability protocols, models, and registry maps (risk #2)."""

from plugins.models import PreviewData, RemoteMetadataResult


class TestCapabilityModels:
    def test_preview_data_defaults(self):
        d = PreviewData(source="ehentai")
        assert d.title is None and d.tags is None and d.rating is None

    def test_remote_metadata_result_defaults_to_ok(self):
        r = RemoteMetadataResult()
        assert r.status == "ok" and r.scalar_values == {} and r.tags is None

    def test_remote_metadata_result_error_carries_reason(self):
        r = RemoteMetadataResult(status="error", reason="fetch_failed")
        assert r.status == "error" and r.reason == "fetch_failed"

    def test_discovered_works_defaults(self):
        from plugins.models import DiscoveredWorks

        d = DiscoveredWorks()
        assert d.works == [] and d.latest_id is None and d.job_options == {}


class TestRegistryCapabilityMaps:
    def test_fresh_registry_has_no_capabilities(self):
        from plugins.registry import PluginRegistry

        r = PluginRegistry()
        assert r.get_previewer("ehentai") is None
        assert r.get_refresher("ehentai") is None
        assert r.get_subscriber("ehentai") is None
        assert r.list_previewable() == []

    def test_subscribable_requires_discovery_contract(self):
        from plugins.builtin.ehentai.source import EhSourcePlugin
        from plugins.builtin.pixiv.source import PixivSourcePlugin
        from plugins.registry import PluginRegistry

        r = PluginRegistry()
        r.register(EhSourcePlugin())
        r.register(PixivSourcePlugin())
        # legacy check_new_works alone no longer qualifies as Subscribable
        assert r.get_subscriber("ehentai") is None
        assert r.get_subscriber("pixiv") is None

    def test_builtin_eh_registers_previewable_and_refreshable(self):
        from plugins.builtin.ehentai.source import EhSourcePlugin
        from plugins.registry import PluginRegistry

        r = PluginRegistry()
        r.register(EhSourcePlugin())
        assert r.get_previewer("ehentai") is not None
        assert r.get_refresher("ehentai") is not None

    def test_builtin_pixiv_registers_previewable_and_refreshable(self):
        from plugins.builtin.pixiv.source import PixivSourcePlugin
        from plugins.registry import PluginRegistry

        r = PluginRegistry()
        r.register(PixivSourcePlugin())
        assert r.get_previewer("pixiv") is not None
        assert r.get_refresher("pixiv") is not None


class TestEhCapabilities:
    async def test_eh_preview_url_non_gallery_url_returns_none(self):
        from plugins.builtin.ehentai.source import EhSourcePlugin

        assert await EhSourcePlugin().preview_url("https://e-hentai.org/tag/foo") is None

    async def test_eh_preview_url_gallery_url_returns_preview_data(self):
        from unittest.mock import AsyncMock, MagicMock, patch

        from plugins.builtin.ehentai.source import EhSourcePlugin

        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        client.get_gallery_metadata = AsyncMock(
            return_value={
                "title": "T",
                "pages": 20,
                "tags": ["a"],
                "uploader": "u",
                "rating": "4.5",
                "thumb": "http://t",
                "category": "Doujinshi",
            }
        )
        with patch("plugins.builtin.ehentai.browse._make_client", AsyncMock(return_value=client)):
            data = await EhSourcePlugin().preview_url("https://e-hentai.org/g/123/abcdef1234/")
        assert data is not None and data.source == "ehentai" and data.pages == 20 and data.rating == 4.5

    async def test_eh_fetch_remote_metadata_expunged_maps_status(self):
        from unittest.mock import AsyncMock, MagicMock, patch

        from plugins.builtin.ehentai.source import EhSourcePlugin

        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        client.get_gallery_metadata = AsyncMock(side_effect=ValueError("gallery expunged"))
        with patch("plugins.builtin.ehentai.browse._make_client", AsyncMock(return_value=client)):
            r = await EhSourcePlugin().fetch_remote_metadata("123", "https://e-hentai.org/g/123/abcdef1234/")
        assert r.status == "expunged"

    async def test_eh_fetch_remote_metadata_no_source_url_skips(self):
        from plugins.builtin.ehentai.source import EhSourcePlugin

        r = await EhSourcePlugin().fetch_remote_metadata("123", None)
        assert r.status == "skipped" and r.reason == "no_source_url"


class TestPixivCapabilities:
    async def test_pixiv_preview_url_without_token_returns_none(self):
        from unittest.mock import AsyncMock, patch

        from plugins.builtin.pixiv.source import PixivSourcePlugin

        with patch("services.credential.get_credential", AsyncMock(return_value=None)):
            assert await PixivSourcePlugin().preview_url("https://www.pixiv.net/artworks/123") is None

    async def test_pixiv_fetch_remote_metadata_without_token_skips(self):
        from unittest.mock import AsyncMock, patch

        from plugins.builtin.pixiv.source import PixivSourcePlugin

        with patch("services.credential.get_credential", AsyncMock(return_value=None)):
            r = await PixivSourcePlugin().fetch_remote_metadata("123", None)
        assert r.status == "skipped" and r.reason == "credentials_required"

    async def test_pixiv_fetch_remote_metadata_bad_source_id_skips(self):
        from unittest.mock import AsyncMock, patch

        from plugins.builtin.pixiv.source import PixivSourcePlugin

        with patch("services.credential.get_credential", AsyncMock(return_value="tok")):
            r = await PixivSourcePlugin().fetch_remote_metadata("not-a-number", None)
        assert r.status == "skipped" and r.reason == "invalid_source_id"


class TestFanboxSubscribable:
    def test_fanbox_registers_subscribable(self):
        from plugins.builtin.fanbox.source import FanboxSourcePlugin
        from plugins.registry import PluginRegistry

        r = PluginRegistry()
        r.register(FanboxSourcePlugin())
        assert r.get_subscriber("fanbox") is not None

    def test_subscription_identity_extracts_creator(self):
        from plugins.builtin.fanbox.source import FanboxSourcePlugin

        p = FanboxSourcePlugin()
        assert p.subscription_identity("https://www.fanbox.cc/@artist") == "artist"
        assert p.subscription_identity("https://example.com/") is None

    async def test_discover_new_works_downgrades_policy_without_credentials(self):
        from unittest.mock import patch

        from plugins.builtin.fanbox.source import FanboxSourcePlugin
        from plugins.models import NewWork

        p = FanboxSourcePlugin()
        seen = {}

        async def _fake_discover(url, last_known, policy, credentials):
            seen["policy"] = policy
            return ([NewWork(url="https://www.fanbox.cc/@artist/posts/1", source_id="1")], "1")

        with patch.object(FanboxSourcePlugin, "discover_posts", side_effect=_fake_discover):
            result = await p.discover_new_works(
                "https://www.fanbox.cc/@artist", None, {"fanbox": {"content": "accessible"}}, None
            )
        assert seen["policy"].content == "free_only"  # downgraded for selection
        assert result.job_options["fanbox"]["content"] == "accessible"  # original policy recorded
        assert result.latest_id == "1" and len(result.works) == 1
