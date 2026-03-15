"""Tests for routers/rss.py.

Covers:
- rss_recent: valid token returns Atom XML feed
- rss_recent: missing token returns 422 (no query param)
- rss_recent: invalid token returns 401
- rss_recent: empty gallery table returns feed with no entries
- rss_recent: gallery entries appear as <entry> elements
- rss_subscription: valid subscription returns Atom feed
- rss_subscription: subscription belonging to different user returns 404
- rss_subscription: nonexistent subscription returns 404
"""

from __future__ import annotations

import hashlib
import os
import sys
from contextlib import ExitStack
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure backend is on the path
_backend_dir = os.path.join(os.path.dirname(__file__), "..")
if os.path.abspath(_backend_dir) not in sys.path:
    sys.path.insert(0, os.path.abspath(_backend_dir))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def _insert_token(db_session, user_id: int = 1, token: str = "test-rss-token") -> str:
    """Insert a user + api_token row for RSS auth and return the raw token."""
    from sqlalchemy import text

    await db_session.execute(
        text(
            "INSERT OR IGNORE INTO users (id, username, email, password_hash, role) "
            "VALUES (:id, :username, :email, :pw, 'admin')"
        ),
        {"id": user_id, "username": f"user{user_id}", "email": None, "pw": "hash"},
    )
    await db_session.execute(
        text(
            "INSERT OR REPLACE INTO api_tokens (id, user_id, name, token_hash) "
            "VALUES (:id, :user_id, 'rss', :hash)"
        ),
        {"id": f"tok-{user_id}", "user_id": user_id, "hash": _token_hash(token)},
    )
    await db_session.commit()
    return token


async def _insert_gallery(db_session, gallery_id: int = 1, title: str = "Test Gallery") -> None:
    """Insert a minimal gallery row."""
    from sqlalchemy import text

    await db_session.execute(
        text(
            "INSERT OR REPLACE INTO galleries "
            "(id, source, source_id, title, download_status, visibility, tags_array) "
            "VALUES (:id, 'pixiv', :src_id, :title, 'proxy_only', 'public', '[]')"
        ),
        {"id": gallery_id, "src_id": str(gallery_id), "title": title},
    )
    await db_session.commit()


async def _insert_subscription(
    db_session,
    sub_id: int = 1,
    user_id: int = 1,
    name: str = "Test Sub",
) -> None:
    """Insert a minimal subscription row."""
    from sqlalchemy import text

    await db_session.execute(
        text(
            "INSERT OR REPLACE INTO subscriptions "
            "(id, user_id, name, url, enabled) "
            "VALUES (:id, :uid, :name, 'https://pixiv.net/user/1', 1)"
        ),
        {"id": sub_id, "uid": user_id, "name": name},
    )
    await db_session.commit()


# ---------------------------------------------------------------------------
# rss_client fixture — like `client` but also patches routers.rss.async_session
# ---------------------------------------------------------------------------


@pytest.fixture
async def rss_client(db_session, db_session_factory, mock_redis):
    """AsyncClient that patches routers.rss.async_session to use the test DB."""
    import main as _main_mod
    from httpx import ASGITransport, AsyncClient
    from core.auth import require_auth

    _app = _main_mod.app

    async def _override_get_db():
        yield db_session

    # We do NOT override require_auth here because RSS uses its own token-based auth.
    # We only need routers.rss.async_session patched.

    _patches = [
        patch("core.redis_client.get_redis", return_value=mock_redis),
        patch("core.rate_limit.get_redis", return_value=mock_redis),
        patch("core.rate_limit.check_rate_limit", new_callable=AsyncMock),
        patch("routers.auth.get_redis", return_value=mock_redis),
        patch("routers.auth.check_rate_limit", new_callable=AsyncMock),
        patch("routers.auth.async_session", db_session_factory),
        patch("routers.rss.async_session", db_session_factory),
        # core.auth.async_session is used by _verify_rss_token indirectly via the
        # async_session import inside rss.py (already patched above)
    ]

    with ExitStack() as stack:
        for p in _patches:
            stack.enter_context(p)
        transport = ASGITransport(app=_app, raise_app_exceptions=False)
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as ac:
            yield ac


# ---------------------------------------------------------------------------
# Tests: GET /api/rss/recent
# ---------------------------------------------------------------------------


class TestRssRecent:
    """Tests for GET /api/rss/recent."""

    async def test_missing_token_returns_422(self, rss_client):
        """Requests without ?token= should fail with 422 (missing required query param)."""
        resp = await rss_client.get("/api/rss/recent")

        assert resp.status_code == 422

    async def test_invalid_token_returns_401(self, rss_client, db_session):
        """An unknown token should return 401."""
        await _insert_token(db_session)

        resp = await rss_client.get("/api/rss/recent?token=wrong-token")

        assert resp.status_code == 401

    async def test_valid_token_returns_200_atom_xml(self, rss_client, db_session):
        """A valid API token should return 200 with Atom XML content."""
        token = await _insert_token(db_session)

        resp = await rss_client.get(f"/api/rss/recent?token={token}")

        assert resp.status_code == 200
        assert "application/atom+xml" in resp.headers["content-type"]

    async def test_valid_token_returns_atom_feed_structure(self, rss_client, db_session):
        """The Atom feed should have the correct namespace and <feed> root element."""
        token = await _insert_token(db_session)

        resp = await rss_client.get(f"/api/rss/recent?token={token}")

        body = resp.text
        assert "http://www.w3.org/2005/Atom" in body
        assert "<title>" in body
        assert "Jyzrox" in body

    async def test_empty_gallery_table_returns_feed_with_no_entries(self, rss_client, db_session):
        """With no galleries, the feed should have zero <entry> elements."""
        token = await _insert_token(db_session)

        resp = await rss_client.get(f"/api/rss/recent?token={token}")

        assert resp.status_code == 200
        body = resp.text
        assert "<entry" not in body

    async def test_gallery_appears_in_feed_as_entry(self, rss_client, db_session):
        """A gallery in the DB should appear as an Atom <entry> in the feed."""
        token = await _insert_token(db_session)
        await _insert_gallery(db_session, gallery_id=10, title="My Gallery")

        resp = await rss_client.get(f"/api/rss/recent?token={token}")

        assert resp.status_code == 200
        body = resp.text
        assert "<entry" in body
        assert "My Gallery" in body

    async def test_xml_declaration_present_in_response(self, rss_client, db_session):
        """The response should include an XML declaration."""
        token = await _insert_token(db_session)

        resp = await rss_client.get(f"/api/rss/recent?token={token}")

        assert resp.status_code == 200
        assert "<?xml" in resp.text


# ---------------------------------------------------------------------------
# Tests: GET /api/rss/subscriptions/{sub_id}
# ---------------------------------------------------------------------------


class TestRssSubscription:
    """Tests for GET /api/rss/subscriptions/{sub_id}."""

    async def test_valid_subscription_returns_atom_feed(self, rss_client, db_session):
        """Owner accessing their subscription's RSS feed should get 200 Atom XML."""
        token = await _insert_token(db_session, user_id=1)
        await _insert_subscription(db_session, sub_id=1, user_id=1)

        resp = await rss_client.get(f"/api/rss/subscriptions/1?token={token}")

        assert resp.status_code == 200
        assert "application/atom+xml" in resp.headers["content-type"]

    async def test_nonexistent_subscription_returns_404(self, rss_client, db_session):
        """Requesting a non-existent subscription ID should return 404."""
        token = await _insert_token(db_session, user_id=1)

        resp = await rss_client.get(f"/api/rss/subscriptions/9999?token={token}")

        assert resp.status_code == 404

    async def test_subscription_owned_by_other_user_returns_404(
        self, rss_client, db_session
    ):
        """A subscription belonging to user_id=2 should return 404 for user_id=1."""
        # Insert user 1's token
        token = await _insert_token(db_session, user_id=1)
        # Insert user 2's subscription
        await db_session.execute(
            __import__("sqlalchemy").text(
                "INSERT OR IGNORE INTO users (id, username, password_hash, role) "
                "VALUES (2, 'user2', 'hash', 'viewer')"
            )
        )
        await db_session.commit()
        await _insert_subscription(db_session, sub_id=5, user_id=2, name="Other User Sub")

        resp = await rss_client.get(f"/api/rss/subscriptions/5?token={token}")

        assert resp.status_code == 404

    async def test_subscription_feed_contains_feed_title(self, rss_client, db_session):
        """The subscription feed title should include the subscription name."""
        token = await _insert_token(db_session, user_id=1)
        await _insert_subscription(db_session, sub_id=2, user_id=1, name="My Artist Feed")

        resp = await rss_client.get(f"/api/rss/subscriptions/2?token={token}")

        assert resp.status_code == 200
        assert "My Artist Feed" in resp.text
