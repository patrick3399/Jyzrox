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
