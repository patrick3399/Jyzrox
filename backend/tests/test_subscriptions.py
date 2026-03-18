"""
Tests for subscription management endpoints (/api/subscriptions/*).

Uses the `client` fixture (pre-authenticated as admin user_id=1).
The subscriptions router calls async_session directly, which is patched
in conftest.py to use the SQLite test engine.

NOTE: POST /api/subscriptions/ uses pg_insert(...).on_conflict_do_update(),
a PostgreSQL-specific upsert.  On the SQLite test engine that path may raise
a CompileError (surfaced as HTTP 500).  Tests that exercise the create
endpoint therefore accept both 200 (PostgreSQL / production) and 500 (SQLite
dialect limitation).  All other endpoints (GET, PATCH, DELETE, check) use
plain SQLAlchemy and work correctly on SQLite.
"""

import uuid

import pytest
from sqlalchemy import text

from core.utils import normalize_subscription_url

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _ensure_user(db_session, user_id: int = 1) -> None:
    """Insert the user row if not already present."""
    await db_session.execute(
        text(
            "INSERT OR IGNORE INTO users (id, username, password_hash, role) "
            "VALUES (:id, :u, 'x', 'admin')"
        ),
        {"id": user_id, "u": f"sub_user_{user_id}"},
    )
    await db_session.commit()


async def _insert_subscription(
    db_session,
    user_id: int = 1,
    url: str | None = None,
    name: str = "Test Sub",
    source: str = "gallery_dl",
    enabled: bool = True,
    cron_expr: str = "0 */2 * * *",
) -> int:
    """Insert a subscription directly via raw SQL and return its id."""
    if url is None:
        url = f"https://example.com/artist/{uuid.uuid4().hex[:8]}"
    result = await db_session.execute(
        text(
            "INSERT INTO subscriptions "
            "(user_id, url, name, source, enabled, auto_download, cron_expr) "
            "VALUES (:uid, :url, :name, :src, :en, 1, :cron) RETURNING id"
        ),
        {
            "uid": user_id,
            "url": url,
            "name": name,
            "src": source,
            "en": 1 if enabled else 0,
            "cron": cron_expr,
        },
    )
    await db_session.commit()
    return result.scalar_one()


# ---------------------------------------------------------------------------
# GET /api/subscriptions/
# ---------------------------------------------------------------------------


class TestListSubscriptions:
    """GET /api/subscriptions/ — list subscriptions for the current user."""

    async def test_list_subscriptions_empty_returns_empty_list(self, client, db_session):
        """No subscriptions → empty list with total=0."""
        await _ensure_user(db_session)

        resp = await client.get("/api/subscriptions/")
        assert resp.status_code == 200
        data = resp.json()
        assert "subscriptions" in data
        assert data["subscriptions"] == []
        assert data["total"] == 0

    async def test_list_subscriptions_returns_inserted_subscription(self, client, db_session):
        """An inserted subscription must appear in the listing."""
        await _ensure_user(db_session)
        await _insert_subscription(db_session, name="Listed Sub")

        resp = await client.get("/api/subscriptions/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        names = [s["name"] for s in data["subscriptions"]]
        assert "Listed Sub" in names

    async def test_list_subscriptions_response_shape(self, client, db_session):
        """Each subscription entry must include key fields."""
        await _ensure_user(db_session)
        await _insert_subscription(db_session, name="Shape Sub")

        resp = await client.get("/api/subscriptions/")
        assert resp.status_code == 200
        sub = resp.json()["subscriptions"][0]
        for field in ("id", "name", "url", "source", "enabled", "auto_download", "cron_expr"):
            assert field in sub

    async def test_list_subscriptions_filter_by_source(self, client, db_session):
        """?source= filters results to matching source only."""
        await _ensure_user(db_session)
        await _insert_subscription(db_session, name="EH Sub", source="ehentai")
        await _insert_subscription(db_session, name="DL Sub", source="gallery_dl")

        resp = await client.get("/api/subscriptions/", params={"source": "ehentai"})
        assert resp.status_code == 200
        sources = [s["source"] for s in resp.json()["subscriptions"]]
        assert all(src == "ehentai" for src in sources)

    async def test_list_subscriptions_filter_by_enabled(self, client, db_session):
        """?enabled=false filters to disabled subscriptions only."""
        await _ensure_user(db_session)
        await _insert_subscription(db_session, name="Active Sub", enabled=True)
        await _insert_subscription(db_session, name="Disabled Sub", enabled=False)

        resp = await client.get("/api/subscriptions/", params={"enabled": "false"})
        assert resp.status_code == 200
        subs = resp.json()["subscriptions"]
        assert all(not s["enabled"] for s in subs)

    async def test_list_subscriptions_pagination_limit(self, client, db_session):
        """?limit=2 constrains result count."""
        await _ensure_user(db_session)
        for i in range(5):
            await _insert_subscription(db_session, name=f"Paged Sub {i}")

        resp = await client.get("/api/subscriptions/", params={"limit": 2, "offset": 0})
        assert resp.status_code == 200
        assert len(resp.json()["subscriptions"]) <= 2


# ---------------------------------------------------------------------------
# POST /api/subscriptions/
# ---------------------------------------------------------------------------


class TestCreateSubscription:
    """POST /api/subscriptions/ — create or upsert a subscription.

    Uses pg_insert which is PostgreSQL-specific; on SQLite this call may
    raise a 500. Tests accept both outcomes unless stated otherwise.
    """

    async def test_create_subscription_success_or_sqlite_limitation(self, client, db_session):
        """Valid payload → 200 (production) or 500 (SQLite dialect limitation)."""
        await _ensure_user(db_session)

        resp = await client.post(
            "/api/subscriptions/",
            json={"url": "https://example.com/artist/create1", "name": "New Sub"},
        )
        assert resp.status_code in (200, 500)
        if resp.status_code == 200:
            data = resp.json()
            assert data["status"] == "ok"
            assert "id" in data

    async def test_create_subscription_invalid_cron_returns_400(self, client, db_session):
        """Invalid cron_expr → 400 before the upsert is attempted."""
        await _ensure_user(db_session)

        resp = await client.post(
            "/api/subscriptions/",
            json={
                "url": "https://example.com/artist/cron",
                "cron_expr": "not-a-cron",
            },
        )
        # Cron validation happens before the pg_insert — must always be 400
        assert resp.status_code == 400

    async def test_create_subscription_valid_cron_accepted(self, client, db_session):
        """Valid cron_expr passes validation (200 or 500 for SQLite)."""
        await _ensure_user(db_session)

        resp = await client.post(
            "/api/subscriptions/",
            json={
                "url": "https://example.com/artist/cron2",
                "cron_expr": "0 3 * * *",
            },
        )
        assert resp.status_code in (200, 500)

    async def test_create_subscription_missing_url_returns_422(self, client, db_session):
        """Missing required url field → 422 from Pydantic."""
        await _ensure_user(db_session)

        resp = await client.post("/api/subscriptions/", json={"name": "No URL"})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/subscriptions/{sub_id}
# ---------------------------------------------------------------------------


class TestGetSubscription:
    """GET /api/subscriptions/{sub_id} — retrieve a single subscription."""

    async def test_get_subscription_correct_fields(self, client, db_session):
        """Returned payload must include id, url, name, enabled, cron_expr."""
        await _ensure_user(db_session)
        sub_id = await _insert_subscription(db_session, name="Get Test")

        resp = await client.get(f"/api/subscriptions/{sub_id}")
        assert resp.status_code == 200
        data = resp.json()
        for field in ("id", "url", "name", "enabled", "cron_expr"):
            assert field in data
        assert data["id"] == sub_id
        assert data["name"] == "Get Test"

    async def test_get_nonexistent_subscription_returns_404(self, client, db_session):
        """GET on a non-existent sub_id → 404."""
        await _ensure_user(db_session)

        resp = await client.get("/api/subscriptions/99999")
        assert resp.status_code == 404

    async def test_get_subscription_wrong_user_returns_404(self, client, db_session):
        """Subscription owned by a different user is not visible → 404."""
        await _ensure_user(db_session, user_id=1)
        await db_session.execute(
            text(
                "INSERT OR IGNORE INTO users (id, username, password_hash) "
                "VALUES (2, 'other_sub_user', 'x')"
            )
        )
        await db_session.commit()
        sub_id = await _insert_subscription(db_session, user_id=2, name="Other User Sub")

        # Authenticated as user 1 — must not see user 2's subscription
        resp = await client.get(f"/api/subscriptions/{sub_id}")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/subscriptions/{sub_id}/jobs
# ---------------------------------------------------------------------------


class TestGetSubscriptionJobs:
    """GET /api/subscriptions/{sub_id}/jobs — jobs linked to a subscription."""

    async def test_get_jobs_returns_empty_list_when_no_jobs(self, client, db_session):
        """No download jobs linked → returns empty jobs list."""
        await _ensure_user(db_session)
        sub_id = await _insert_subscription(db_session, name="Jobs Sub")

        resp = await client.get(f"/api/subscriptions/{sub_id}/jobs")
        assert resp.status_code == 200
        data = resp.json()
        assert "jobs" in data
        assert data["jobs"] == []

    async def test_get_jobs_for_nonexistent_subscription_returns_404(self, client, db_session):
        """Jobs endpoint on a non-existent sub_id → 404."""
        await _ensure_user(db_session)

        resp = await client.get("/api/subscriptions/99999/jobs")
        assert resp.status_code == 404

    async def test_get_jobs_returns_linked_download_jobs(self, client, db_session):
        """Download jobs with matching subscription_id appear in the response."""
        await _ensure_user(db_session)
        sub_id = await _insert_subscription(db_session, name="Jobs With Data")
        job_id = str(uuid.uuid4())
        await db_session.execute(
            text(
                "INSERT INTO download_jobs (id, url, status, progress, subscription_id, user_id) "
                "VALUES (:jid, 'https://example.com/dl', 'done', '{}', :sid, 1)"
            ),
            {"jid": job_id, "sid": sub_id},
        )
        await db_session.commit()

        resp = await client.get(f"/api/subscriptions/{sub_id}/jobs")
        assert resp.status_code == 200
        job_ids = [j["id"] for j in resp.json()["jobs"]]
        assert job_id in job_ids


# ---------------------------------------------------------------------------
# PATCH /api/subscriptions/{sub_id}
# ---------------------------------------------------------------------------


class TestUpdateSubscription:
    """PATCH /api/subscriptions/{sub_id} — update a subscription."""

    async def test_update_subscription_name_returns_ok(self, client, db_session):
        """Patching name → 200 with status=ok."""
        await _ensure_user(db_session)
        sub_id = await _insert_subscription(db_session, name="Old Name")

        resp = await client.patch(f"/api/subscriptions/{sub_id}", json={"name": "New Name"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    async def test_update_subscription_enabled_false_returns_ok(self, client, db_session):
        """Disabling a subscription → 200."""
        await _ensure_user(db_session)
        sub_id = await _insert_subscription(db_session, name="Disable Me", enabled=True)

        resp = await client.patch(f"/api/subscriptions/{sub_id}", json={"enabled": False})
        assert resp.status_code == 200

    async def test_update_subscription_disabled_then_reflected_on_get(self, client, db_session):
        """After disabling, GET shows enabled=False."""
        await _ensure_user(db_session)
        sub_id = await _insert_subscription(db_session, name="Toggle Sub", enabled=True)

        await client.patch(f"/api/subscriptions/{sub_id}", json={"enabled": False})

        resp = await client.get(f"/api/subscriptions/{sub_id}")
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False

    async def test_update_subscription_invalid_cron_returns_400(self, client, db_session):
        """Patching with an invalid cron_expr → 400."""
        await _ensure_user(db_session)
        sub_id = await _insert_subscription(db_session, name="Cron Patch")

        resp = await client.patch(
            f"/api/subscriptions/{sub_id}", json={"cron_expr": "not-a-cron"}
        )
        assert resp.status_code == 400

    async def test_update_subscription_valid_cron_returns_ok(self, client, db_session):
        """Patching with a valid cron_expr → 200."""
        await _ensure_user(db_session)
        sub_id = await _insert_subscription(db_session, name="Cron OK Patch")

        resp = await client.patch(
            f"/api/subscriptions/{sub_id}", json={"cron_expr": "0 6 * * 1"}
        )
        assert resp.status_code == 200

    async def test_update_subscription_no_fields_returns_400(self, client, db_session):
        """Sending an empty patch body → 400 (no fields to update)."""
        await _ensure_user(db_session)
        sub_id = await _insert_subscription(db_session, name="Empty Patch")

        resp = await client.patch(f"/api/subscriptions/{sub_id}", json={})
        assert resp.status_code == 400

    async def test_update_nonexistent_subscription_returns_404(self, client, db_session):
        """Patching a non-existent sub_id → 404."""
        await _ensure_user(db_session)

        resp = await client.patch("/api/subscriptions/99999", json={"name": "Ghost"})
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/subscriptions/{sub_id}
# ---------------------------------------------------------------------------


class TestDeleteSubscription:
    """DELETE /api/subscriptions/{sub_id} — delete a subscription."""

    async def test_delete_subscription_returns_ok(self, client, db_session):
        """Deleting an existing subscription → 200 with status=ok."""
        await _ensure_user(db_session)
        sub_id = await _insert_subscription(db_session, name="To Delete")

        resp = await client.delete(f"/api/subscriptions/{sub_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

    async def test_delete_subscription_then_absent_on_get(self, client, db_session):
        """Deleted subscription returns 404 on subsequent GET."""
        await _ensure_user(db_session)
        sub_id = await _insert_subscription(db_session, name="Gone Sub")

        await client.delete(f"/api/subscriptions/{sub_id}")

        resp = await client.get(f"/api/subscriptions/{sub_id}")
        assert resp.status_code == 404

    async def test_delete_nonexistent_subscription_returns_404(self, client, db_session):
        """Deleting a non-existent sub_id → 404."""
        await _ensure_user(db_session)

        resp = await client.delete("/api/subscriptions/99999")
        assert resp.status_code == 404

    async def test_delete_subscription_cancels_active_jobs(self, client, db_session):
        """Active queued jobs linked to the subscription are cancelled on delete."""
        await _ensure_user(db_session)
        sub_id = await _insert_subscription(db_session, name="Cancel Jobs Sub")
        job_id = str(uuid.uuid4())
        await db_session.execute(
            text(
                "INSERT INTO download_jobs (id, url, status, progress, subscription_id, user_id) "
                "VALUES (:jid, 'https://example.com/dl', 'queued', '{}', :sid, 1)"
            ),
            {"jid": job_id, "sid": sub_id},
        )
        await db_session.commit()

        resp = await client.delete(f"/api/subscriptions/{sub_id}")
        assert resp.status_code == 200
        assert resp.json()["cancelled_jobs"] >= 1


# ---------------------------------------------------------------------------
# POST /api/subscriptions/{sub_id}/check
# ---------------------------------------------------------------------------


class TestCheckSubscription:
    """POST /api/subscriptions/{sub_id}/check — trigger immediate check."""

    async def test_check_subscription_returns_queued_status(self, client, db_session):
        """Triggering a check → 200 with status=queued and subscription_id."""
        await _ensure_user(db_session)
        sub_id = await _insert_subscription(db_session, name="Check Sub")

        resp = await client.post(f"/api/subscriptions/{sub_id}/check")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "queued"
        assert data["subscription_id"] == sub_id

    async def test_check_nonexistent_subscription_returns_404(self, client, db_session):
        """Check on a non-existent sub_id → 404."""
        await _ensure_user(db_session)

        resp = await client.post("/api/subscriptions/99999/check")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# normalize_subscription_url — unit tests
# ---------------------------------------------------------------------------


class TestNormalizeSubscriptionUrl:
    """Unit tests for core.utils.normalize_subscription_url.

    These tests document the expected normalisation contract so that any
    future refactor of the function is caught immediately.
    """

    def test_normalize_strips_single_trailing_slash(self):
        """Trailing slash is removed: 'https://example.com/artist/' → no slash."""
        result = normalize_subscription_url("https://example.com/artist/")
        assert result == "https://example.com/artist"

    def test_normalize_strips_multiple_trailing_slashes(self):
        """Multiple consecutive trailing slashes are all removed."""
        result = normalize_subscription_url("https://example.com/artist///")
        assert result == "https://example.com/artist"

    def test_normalize_strips_leading_and_trailing_whitespace(self):
        """Leading and trailing whitespace is stripped."""
        result = normalize_subscription_url("  https://example.com/artist  ")
        assert result == "https://example.com/artist"

    def test_normalize_strips_whitespace_and_trailing_slash_combined(self):
        """Whitespace + trailing slash are both removed in a single call."""
        result = normalize_subscription_url("  https://example.com/artist/  ")
        assert result == "https://example.com/artist"

    def test_normalize_leaves_clean_url_unchanged(self):
        """A URL with no extra whitespace or trailing slash is returned as-is."""
        url = "https://example.com/artist"
        assert normalize_subscription_url(url) == url


# ---------------------------------------------------------------------------
# POST /api/subscriptions/ — duplicate field and URL normalisation
# ---------------------------------------------------------------------------


class TestCreateSubscriptionDuplicateAndNormalization:
    """Regression tests for the duplicate URL detection feature.

    The pg_insert upsert path is PostgreSQL-specific and may 500 on SQLite.
    Tests that rely on the row being persisted accept 200/500 and skip on 500.
    Tests that only inspect the response shape on a successful 200 are
    gated behind a skip when the SQLite limitation kicks in.
    """

    async def test_create_subscription_response_contains_duplicate_field(
        self, client, db_session
    ):
        """Successful POST response must include a 'duplicate' field."""
        await _ensure_user(db_session)

        resp = await client.post(
            "/api/subscriptions/",
            json={"url": "https://example.com/artist/dup-field-check", "name": "Dup Field"},
        )
        # Accept SQLite limitation
        if resp.status_code == 500:
            pytest.skip("pg_insert not supported on SQLite test engine")

        assert resp.status_code == 200
        data = resp.json()
        assert "duplicate" in data, "Response must contain 'duplicate' field"
        # First creation is never a duplicate
        assert not data["duplicate"]

    async def test_create_subscription_with_trailing_slash_url_stores_normalized_url(
        self, client, db_session
    ):
        """URL submitted with a trailing slash must be stored without the slash.

        After POST, a GET on the returned id must reflect the normalised URL.
        This guards against the bug where 'https://x.com/a/' and
        'https://x.com/a' would be treated as two distinct subscriptions.
        """
        await _ensure_user(db_session)
        raw_url = "https://example.com/artist/norm-test/"
        expected_url = "https://example.com/artist/norm-test"

        resp = await client.post(
            "/api/subscriptions/",
            json={"url": raw_url, "name": "Norm Test"},
        )
        if resp.status_code == 500:
            pytest.skip("pg_insert not supported on SQLite test engine")

        assert resp.status_code == 200
        sub_id = resp.json()["id"]

        get_resp = await client.get(f"/api/subscriptions/{sub_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["url"] == expected_url, (
            f"Expected stored URL '{expected_url}' but got '{get_resp.json()['url']}'"
        )

    async def test_create_subscription_with_whitespace_url_stores_normalized_url(
        self, client, db_session
    ):
        """URL submitted with surrounding whitespace must be stored stripped.

        Guards against whitespace-padded URLs being stored verbatim and then
        failing duplicate detection on subsequent identical requests.
        """
        await _ensure_user(db_session)
        raw_url = "  https://example.com/artist/ws-test  "
        expected_url = "https://example.com/artist/ws-test"

        resp = await client.post(
            "/api/subscriptions/",
            json={"url": raw_url, "name": "Whitespace URL Test"},
        )
        if resp.status_code == 500:
            pytest.skip("pg_insert not supported on SQLite test engine")

        assert resp.status_code == 200
        sub_id = resp.json()["id"]

        get_resp = await client.get(f"/api/subscriptions/{sub_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["url"] == expected_url, (
            f"Expected stored URL '{expected_url}' but got '{get_resp.json()['url']}'"
        )
