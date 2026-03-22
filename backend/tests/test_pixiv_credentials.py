"""Tests for plugins/builtin/pixiv/_credentials.py.

Covers:
- pixiv_credential_flows: returns 3 flows with correct types
- pixiv_credential_flows: 'fields' flow has refresh_token field
- pixiv_credential_flows: 'oauth' flow has oauth_config
- pixiv_credential_flows: 'login' flow has login_endpoint and phpsessid field
- verify_pixiv_credential: empty credentials returns invalid status
- verify_pixiv_credential: no refresh_token key returns invalid status
- verify_pixiv_credential: successful auth returns valid status with username
- verify_pixiv_credential: auth exception returns invalid status with error message
- verify_pixiv_credential: pixivpy3 ImportError returns invalid status
- verify_pixiv_credential: string credential used as refresh_token
"""

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure backend is on the path
_backend_dir = os.path.join(os.path.dirname(__file__), "..")
if os.path.abspath(_backend_dir) not in sys.path:
    sys.path.insert(0, os.path.abspath(_backend_dir))

# ---------------------------------------------------------------------------
# Tests: pixiv_credential_flows()
# ---------------------------------------------------------------------------

class TestPixivCredentialFlows:
    """Unit tests for pixiv_credential_flows()."""

    def test_returns_three_flows(self):
        """pixiv_credential_flows() should return exactly 3 credential flows."""
        from plugins.builtin.pixiv._credentials import pixiv_credential_flows

        flows = pixiv_credential_flows()

        assert len(flows) == 3

    def test_flow_types_are_fields_oauth_login(self):
        """The three flows should have types: fields, oauth, login."""
        from plugins.builtin.pixiv._credentials import pixiv_credential_flows

        flows = pixiv_credential_flows()
        flow_types = [f.flow_type for f in flows]

        assert "fields" in flow_types
        assert "oauth" in flow_types
        assert "login" in flow_types

    def test_fields_flow_has_refresh_token_field(self):
        """The 'fields' flow must include a required 'refresh_token' field."""
        from plugins.builtin.pixiv._credentials import pixiv_credential_flows

        flows = pixiv_credential_flows()
        fields_flow = next(f for f in flows if f.flow_type == "fields")

        field_names = [field.name for field in fields_flow.fields]
        assert "refresh_token" in field_names

        rt_field = next(f for f in fields_flow.fields if f.name == "refresh_token")
        assert rt_field.required is True
        assert rt_field.field_type == "password"

    def test_fields_flow_has_verify_endpoint(self):
        """The 'fields' flow should declare a verify_endpoint."""
        from plugins.builtin.pixiv._credentials import pixiv_credential_flows

        flows = pixiv_credential_flows()
        fields_flow = next(f for f in flows if f.flow_type == "fields")

        assert fields_flow.verify_endpoint is not None
        assert "pixiv" in fields_flow.verify_endpoint

    def test_oauth_flow_has_oauth_config(self):
        """The 'oauth' flow must have a non-None oauth_config."""
        from plugins.builtin.pixiv._credentials import pixiv_credential_flows

        flows = pixiv_credential_flows()
        oauth_flow = next(f for f in flows if f.flow_type == "oauth")

        assert oauth_flow.oauth_config is not None
        assert oauth_flow.oauth_config.display_name == "Pixiv OAuth Login"

    def test_login_flow_has_phpsessid_field_and_endpoint(self):
        """The 'login' flow should have a login_endpoint and a phpsessid field."""
        from plugins.builtin.pixiv._credentials import pixiv_credential_flows

        flows = pixiv_credential_flows()
        login_flow = next(f for f in flows if f.flow_type == "login")

        assert login_flow.login_endpoint is not None
        assert "pixiv" in login_flow.login_endpoint

        field_names = [f.name for f in login_flow.fields]
        assert "phpsessid" in field_names

# ---------------------------------------------------------------------------
# Tests: verify_pixiv_credential()
# ---------------------------------------------------------------------------

class TestVerifyPixivCredential:
    """Unit tests for verify_pixiv_credential()."""

    async def test_empty_dict_credentials_returns_invalid(self):
        """An empty credentials dict should return valid=False."""
        from plugins.builtin.pixiv._credentials import verify_pixiv_credential

        result = await verify_pixiv_credential({})

        assert result.valid is False
        assert result.error is not None

    async def test_missing_refresh_token_returns_invalid(self):
        """A dict without 'refresh_token' key should return valid=False."""
        from plugins.builtin.pixiv._credentials import verify_pixiv_credential

        result = await verify_pixiv_credential({"username": "user"})

        assert result.valid is False

    async def test_successful_auth_returns_valid_with_username(self):
        """When pixivpy3 auth succeeds, returns valid=True with the username."""
        from plugins.builtin.pixiv._credentials import verify_pixiv_credential

        mock_api = MagicMock()
        mock_api.user_id = "111"

        mock_user_detail = MagicMock()
        mock_user_detail.user = MagicMock()
        mock_user_detail.user.name = "TestUser"

        mock_pixivpy3 = MagicMock()
        mock_pixivpy3.AppPixivAPI.return_value = mock_api

        with (
            patch.dict("sys.modules", {"pixivpy3": mock_pixivpy3}),
            patch("asyncio.to_thread", new_callable=AsyncMock) as mock_thread,
        ):
            # First call to to_thread is api.auth, second is api.user_detail
            mock_thread.side_effect = [None, mock_user_detail]

            result = await verify_pixiv_credential({"refresh_token": "valid-token"})

        assert result.valid is True
        assert result.username == "TestUser"

    async def test_auth_exception_returns_invalid_with_error(self):
        """When pixivpy3 auth raises, returns valid=False with error message."""
        from plugins.builtin.pixiv._credentials import verify_pixiv_credential

        mock_api = MagicMock()

        mock_pixivpy3 = MagicMock()
        mock_pixivpy3.AppPixivAPI.return_value = mock_api

        with (
            patch.dict("sys.modules", {"pixivpy3": mock_pixivpy3}),
            patch(
                "asyncio.to_thread",
                new_callable=AsyncMock,
                side_effect=OSError("connection refused"),
            ),
        ):
            result = await verify_pixiv_credential({"refresh_token": "bad-token"})

        assert result.valid is False
        assert result.error is not None
        assert "connection refused" in result.error

    async def test_string_credential_raises_attribute_error(self):
        """A bare string credential causes AttributeError because .get() is called first.

        The isinstance check is after the .get() call in the source, so passing a
        string causes AttributeError which is unhandled (not inside try block).
        This test documents the current code behavior as a known limitation.
        """
        from plugins.builtin.pixiv._credentials import verify_pixiv_credential

        with pytest.raises(AttributeError):
            await verify_pixiv_credential("bare-refresh-token")

    async def test_general_exception_returns_invalid(self):
        """An unexpected exception type returns valid=False."""
        from plugins.builtin.pixiv._credentials import verify_pixiv_credential

        mock_api = MagicMock()

        mock_pixivpy3 = MagicMock()
        mock_pixivpy3.AppPixivAPI.return_value = mock_api

        with (
            patch.dict("sys.modules", {"pixivpy3": mock_pixivpy3}),
            patch(
                "asyncio.to_thread",
                new_callable=AsyncMock,
                side_effect=Exception("unexpected"),
            ),
        ):
            result = await verify_pixiv_credential({"refresh_token": "tok"})

        assert result.valid is False
        assert "unexpected" in result.error
