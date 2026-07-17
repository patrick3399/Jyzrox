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


class TestRegistryCapabilityMaps:
    def test_fresh_registry_has_no_capabilities(self):
        from plugins.registry import PluginRegistry

        r = PluginRegistry()
        assert r.get_previewer("ehentai") is None
        assert r.get_refresher("ehentai") is None
        assert r.get_subscriber("ehentai") is None
        assert r.list_previewable() == []

    def test_builtin_eh_and_pixiv_register_subscribable(self):
        from plugins.builtin.ehentai.source import EhSourcePlugin
        from plugins.builtin.pixiv.source import PixivSourcePlugin
        from plugins.registry import PluginRegistry

        r = PluginRegistry()
        r.register(EhSourcePlugin())
        r.register(PixivSourcePlugin())
        assert r.get_subscriber("ehentai") is not None
        assert r.get_subscriber("pixiv") is not None
