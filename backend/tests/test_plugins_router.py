"""
Integration tests for the plugins router (/api/plugins/).

Uses the `client` fixture (authenticated as admin user_id=1).
list_credentials and plugin_registry are patched so the tests do not
depend on which plugins happen to be registered in the current environment.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _insert_user(db_session):
    await db_session.execute(
        text(
            "INSERT OR IGNORE INTO users (id, username, password_hash, role) "
            "VALUES (1, 'admin', 'hash', 'admin')"
        )
    )
    await db_session.commit()


def _make_plugin_meta(source_id: str = "ehentai", name: str = "E-Hentai"):
    meta = MagicMock()
    meta.source_id = source_id
    meta.name = name
    meta.version = "1.0.0"
    meta.url_patterns = ["https://e-hentai.org/*"]
    meta.credential_schema = []
    return meta


# ---------------------------------------------------------------------------
# Tests — list plugins
# ---------------------------------------------------------------------------


async def test_plugins_list_returns_200(client, db_session, db_session_factory):
    await _insert_user(db_session)
    # list_credentials is imported inside the endpoint function body,
    # so patch it at the module where it is defined.
    with patch(
        "services.credential.list_credentials",
        new_callable=AsyncMock,
        return_value=[],
    ):
        resp = await client.get("/api/plugins/")
    assert resp.status_code == 200


async def test_plugins_list_returns_plugins_array(client, db_session, db_session_factory):
    await _insert_user(db_session)
    meta = _make_plugin_meta("test_source", "Test Plugin")

    with (
        patch("routers.plugins.plugin_registry") as mock_registry,
        patch(
            "services.credential.list_credentials",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        mock_registry.list_plugins.return_value = [meta]
        mock_registry.get_browser.return_value = None
        mock_registry.get_credential_provider.return_value = None

        resp = await client.get("/api/plugins/")

    assert resp.status_code == 200
    data = resp.json()
    assert "plugins" in data
    assert isinstance(data["plugins"], list)
    assert len(data["plugins"]) == 1


async def test_plugins_list_each_plugin_has_required_fields(
    client, db_session, db_session_factory
):
    await _insert_user(db_session)
    meta = _make_plugin_meta("test_source", "Test Plugin")

    with (
        patch("routers.plugins.plugin_registry") as mock_registry,
        patch(
            "services.credential.list_credentials",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        mock_registry.list_plugins.return_value = [meta]
        mock_registry.get_browser.return_value = None
        mock_registry.get_credential_provider.return_value = None

        resp = await client.get("/api/plugins/")

    assert resp.status_code == 200
    plugin = resp.json()["plugins"][0]
    assert "source_id" in plugin
    assert "name" in plugin
    assert "enabled" in plugin
    assert plugin["source_id"] == "test_source"
    assert plugin["name"] == "Test Plugin"
    assert plugin["enabled"] is True
