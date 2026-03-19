"""Shared test helpers for Jyzrox backend tests."""

from unittest.mock import AsyncMock, MagicMock


def make_mock_site_config_svc():
    """Create a mock SiteConfigService with default DownloadParams.

    Reusable across test files that need to mock site_config_service.
    """
    from core.site_config import DownloadParams

    svc = MagicMock()
    svc.get_effective_download_params = AsyncMock(return_value=DownloadParams())
    svc.get_all_download_params = AsyncMock(return_value={})
    return svc
