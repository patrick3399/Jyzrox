"""Unit tests for services/download_policy.py — shared credential policy."""

from unittest.mock import AsyncMock, MagicMock, patch

from services.download_policy import get_credential_policy


def _cfg(requirement: str, source_id: str = "src", name: str = "Src", warning_code: str | None = "src_warn"):
    cfg = MagicMock()
    cfg.credential_requirement = requirement
    cfg.source_id = source_id
    cfg.name = name
    cfg.credential_warning_code = warning_code
    return cfg


class TestGetCredentialPolicy:
    async def test_required_without_credential_is_missing_required(self):
        with (
            patch("plugins.builtin.gallery_dl._sites.get_site_config", return_value=_cfg("required", name="Pixiv")),
            patch("services.credential.get_credential", new_callable=AsyncMock, return_value=None),
        ):
            policy = await get_credential_policy("pixiv")

        assert policy.missing_required is True
        assert policy.missing_recommended is False
        assert policy.source_name == "Pixiv"
        assert policy.warning_code is None

    async def test_required_with_credential_is_satisfied(self):
        with (
            patch("plugins.builtin.gallery_dl._sites.get_site_config", return_value=_cfg("required")),
            patch("services.credential.get_credential", new_callable=AsyncMock, return_value="token"),
        ):
            policy = await get_credential_policy("pixiv")

        assert policy.missing_required is False
        assert policy.has_credential is True

    async def test_recommended_without_credential_carries_warning_code(self):
        with (
            patch(
                "plugins.builtin.gallery_dl._sites.get_site_config",
                return_value=_cfg("recommended", warning_code="eh_credentials_recommended"),
            ),
            patch("services.credential.get_credential", new_callable=AsyncMock, return_value=None),
        ):
            policy = await get_credential_policy("ehentai")

        assert policy.missing_required is False
        assert policy.missing_recommended is True
        assert policy.warning_code == "eh_credentials_recommended"

    async def test_recommended_with_credential_has_no_warning(self):
        with (
            patch("plugins.builtin.gallery_dl._sites.get_site_config", return_value=_cfg("recommended")),
            patch("services.credential.get_credential", new_callable=AsyncMock, return_value="cookies"),
        ):
            policy = await get_credential_policy("ehentai")

        assert policy.missing_recommended is False
        assert policy.warning_code is None

    async def test_none_requirement_skips_credential_lookup(self):
        """Sources with no credential requirement must not hit the credential store."""
        lookup = AsyncMock(return_value=None)
        with (
            patch("plugins.builtin.gallery_dl._sites.get_site_config", return_value=_cfg("none")),
            patch("services.credential.get_credential", lookup),
        ):
            policy = await get_credential_policy("danbooru")

        lookup.assert_not_awaited()
        assert policy.missing_required is False
        assert policy.missing_recommended is False
        assert policy.warning_code is None
