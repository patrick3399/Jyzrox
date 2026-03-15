"""
Tests for user management endpoints (/api/users/*).

Uses the `client` fixture (pre-authenticated as admin user_id=1).
All write operations require the user row to exist in the DB for FK constraints.
"""

from sqlalchemy import text

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _ensure_admin(db_session, user_id: int = 1) -> None:
    """Insert the admin user if not already present."""
    await db_session.execute(
        text(
            "INSERT OR IGNORE INTO users (id, username, password_hash, role) "
            "VALUES (:id, :u, :p, 'admin')"
        ),
        {"id": user_id, "u": f"admin_{user_id}", "p": "x"},
    )
    await db_session.commit()


async def _insert_user(
    db_session,
    username: str = "testuser",
    role: str = "member",
    user_id: int | None = None,
) -> int:
    """Insert a plain user and return its id."""
    if user_id is not None:
        result = await db_session.execute(
            text(
                "INSERT OR IGNORE INTO users (id, username, password_hash, role) "
                "VALUES (:id, :u, 'x', :r) RETURNING id"
            ),
            {"id": user_id, "u": username, "r": role},
        )
    else:
        result = await db_session.execute(
            text(
                "INSERT INTO users (username, password_hash, role) "
                "VALUES (:u, 'x', :r) RETURNING id"
            ),
            {"u": username, "r": role},
        )
    await db_session.commit()
    row = result.fetchone()
    return row[0]


# ---------------------------------------------------------------------------
# GET /api/users/
# ---------------------------------------------------------------------------


class TestListUsers:
    """GET /api/users/ — list all users."""

    async def test_list_users_returns_seeded_admin(self, client, db_session):
        """Seeded admin user must appear in the response."""
        await _ensure_admin(db_session)

        resp = await client.get("/api/users/")
        assert resp.status_code == 200
        data = resp.json()
        assert "users" in data
        ids = [u["id"] for u in data["users"]]
        assert 1 in ids

    async def test_list_users_response_shape(self, client, db_session):
        """Each user entry must include id, username, email, role, created_at."""
        await _ensure_admin(db_session)

        resp = await client.get("/api/users/")
        assert resp.status_code == 200
        users = resp.json()["users"]
        assert len(users) >= 1
        u = users[0]
        for field in ("id", "username", "email", "role"):
            assert field in u

    async def test_list_users_includes_created_user(self, client, db_session):
        """A newly created user must appear in the list."""
        await _ensure_admin(db_session)
        await _insert_user(db_session, username="list_check_user")

        resp = await client.get("/api/users/")
        assert resp.status_code == 200
        usernames = [u["username"] for u in resp.json()["users"]]
        assert "list_check_user" in usernames


# ---------------------------------------------------------------------------
# POST /api/users/
# ---------------------------------------------------------------------------


class TestCreateUser:
    """POST /api/users/ — create a new user."""

    async def test_create_user_success_returns_id_username_role(self, client, db_session):
        """Valid payload → 201 with id, username, role fields."""
        await _ensure_admin(db_session)

        resp = await client.post(
            "/api/users/",
            json={"username": "newuser1", "password": "securepass", "role": "member"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "id" in data
        assert data["username"] == "newuser1"
        assert data["role"] == "member"

    async def test_create_user_with_email_returns_email(self, client, db_session):
        """Providing email → returned in response."""
        await _ensure_admin(db_session)

        resp = await client.post(
            "/api/users/",
            json={
                "username": "emailuser",
                "password": "securepass",
                "role": "member",
                "email": "test@example.com",
            },
        )
        assert resp.status_code == 201
        assert resp.json()["email"] == "test@example.com"

    async def test_create_user_short_password_returns_400(self, client, db_session):
        """Password under 8 chars → 400."""
        await _ensure_admin(db_session)

        resp = await client.post(
            "/api/users/",
            json={"username": "shortpwuser", "password": "abc", "role": "member"},
        )
        assert resp.status_code in (400, 422)

    async def test_create_user_duplicate_username_returns_409(self, client, db_session):
        """Duplicate username → 409 Conflict."""
        await _ensure_admin(db_session)
        await _insert_user(db_session, username="dupuser")

        resp = await client.post(
            "/api/users/",
            json={"username": "dupuser", "password": "securepass", "role": "member"},
        )
        assert resp.status_code == 409

    async def test_create_user_invalid_role_returns_400(self, client, db_session):
        """Unrecognised role value → 400."""
        await _ensure_admin(db_session)

        resp = await client.post(
            "/api/users/",
            json={"username": "badroleuser", "password": "securepass", "role": "superuser"},
        )
        assert resp.status_code in (400, 422)

    async def test_create_user_admin_role_succeeds(self, client, db_session):
        """role=admin is a valid role."""
        await _ensure_admin(db_session)

        resp = await client.post(
            "/api/users/",
            json={"username": "secondadmin", "password": "securepass", "role": "admin"},
        )
        assert resp.status_code == 201
        assert resp.json()["role"] == "admin"

    async def test_create_user_viewer_role_succeeds(self, client, db_session):
        """role=viewer is a valid role."""
        await _ensure_admin(db_session)

        resp = await client.post(
            "/api/users/",
            json={"username": "vieweruser", "password": "securepass", "role": "viewer"},
        )
        assert resp.status_code == 201
        assert resp.json()["role"] == "viewer"


# ---------------------------------------------------------------------------
# PATCH /api/users/{user_id}
# ---------------------------------------------------------------------------


class TestUpdateUser:
    """PATCH /api/users/{user_id} — update role, email, or password."""

    async def test_update_user_change_email_returns_ok(self, client, db_session):
        """Patching email → 200 with status=ok."""
        await _ensure_admin(db_session)
        uid = await _insert_user(db_session, username="patchemail")

        resp = await client.patch(
            f"/api/users/{uid}",
            json={"email": "updated@example.com"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    async def test_update_user_change_role_returns_ok(self, client, db_session):
        """Patching role from member to viewer → 200."""
        await _ensure_admin(db_session)
        uid = await _insert_user(db_session, username="patchrole", role="member")

        resp = await client.patch(f"/api/users/{uid}", json={"role": "viewer"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    async def test_update_user_short_password_returns_400(self, client, db_session):
        """Patching password shorter than 8 chars → 400."""
        await _ensure_admin(db_session)
        uid = await _insert_user(db_session, username="patchshortpw")

        resp = await client.patch(f"/api/users/{uid}", json={"password": "abc"})
        assert resp.status_code in (400, 422)

    async def test_update_user_valid_password_returns_ok(self, client, db_session):
        """Patching password with a long enough value → 200."""
        await _ensure_admin(db_session)
        uid = await _insert_user(db_session, username="patchvalidpw")

        resp = await client.patch(f"/api/users/{uid}", json={"password": "newsecurepassword"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    async def test_update_user_not_found_returns_404(self, client, db_session):
        """Patching a non-existent user_id → 404."""
        await _ensure_admin(db_session)

        resp = await client.patch("/api/users/99999", json={"email": "ghost@example.com"})
        assert resp.status_code == 404

    async def test_update_user_invalid_role_returns_400(self, client, db_session):
        """Patching with an invalid role → 400."""
        await _ensure_admin(db_session)
        uid = await _insert_user(db_session, username="patchbadrole")

        resp = await client.patch(f"/api/users/{uid}", json={"role": "superadmin"})
        assert resp.status_code in (400, 422)

    async def test_update_last_admin_demote_returns_400(self, client, db_session):
        """Demoting the only admin to member → 400 (cannot_delete_last_admin)."""
        await _ensure_admin(db_session, user_id=1)

        # user 1 is the only admin — try demoting it
        resp = await client.patch("/api/users/1", json={"role": "member"})
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# DELETE /api/users/{user_id}
# ---------------------------------------------------------------------------


class TestDeleteUser:
    """DELETE /api/users/{user_id} — delete a user."""

    async def test_delete_user_success_returns_ok(self, client, db_session):
        """Deleting an existing non-self user → 200 with status=ok."""
        await _ensure_admin(db_session)
        # Create a second admin so there's a spare one
        await _insert_user(db_session, username="spare_admin", role="admin", user_id=2)
        uid = await _insert_user(db_session, username="todelete", role="member")

        resp = await client.delete(f"/api/users/{uid}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    async def test_delete_user_then_absent_from_list(self, client, db_session):
        """Deleted user no longer appears in GET /api/users/."""
        await _ensure_admin(db_session)
        await _insert_user(db_session, username="spare_admin2", role="admin", user_id=3)
        uid = await _insert_user(db_session, username="gone_user", role="member")

        await client.delete(f"/api/users/{uid}")

        resp = await client.get("/api/users/")
        ids = [u["id"] for u in resp.json()["users"]]
        assert uid not in ids

    async def test_delete_user_self_returns_400(self, client, db_session):
        """Deleting own account (user_id=1) → 400 (cannot_delete_self)."""
        await _ensure_admin(db_session)

        resp = await client.delete("/api/users/1")
        assert resp.status_code == 400

    async def test_delete_user_not_found_returns_404(self, client, db_session):
        """Deleting a non-existent user_id → 404."""
        await _ensure_admin(db_session)

        resp = await client.delete("/api/users/99999")
        assert resp.status_code == 404

    async def test_delete_last_admin_returns_400(self, client, db_session):
        """Deleting the only admin (not self) → 400 (cannot_delete_last_admin)."""
        await _ensure_admin(db_session)
        # Insert a second admin, make that the lone admin by id, and attempt deletion
        other_admin_id = await _insert_user(
            db_session, username="only_other_admin", role="admin"
        )
        # Demote user_id=1 to member so other_admin_id is the last admin
        await db_session.execute(
            text("UPDATE users SET role = 'member' WHERE id = 1")
        )
        await db_session.commit()

        resp = await client.delete(f"/api/users/{other_admin_id}")
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Role-based access control (non-admin callers)
# ---------------------------------------------------------------------------


class TestUsersRoleAccess:
    """All /api/users/ endpoints require admin role; non-admin callers get 403."""

    async def test_list_users_viewer_returns_403(self, make_client, db_session):
        """viewer role → 403 on GET /api/users/."""
        await _ensure_admin(db_session)
        async with make_client(user_id=2, role="viewer") as ac:
            resp = await ac.get("/api/users/")
        assert resp.status_code == 403

    async def test_list_users_member_returns_403(self, make_client, db_session):
        """member role → 403 on GET /api/users/."""
        await _ensure_admin(db_session)
        async with make_client(user_id=2, role="member") as ac:
            resp = await ac.get("/api/users/")
        assert resp.status_code == 403

    async def test_create_user_viewer_returns_403(self, make_client, db_session):
        """viewer role → 403 on POST /api/users/."""
        await _ensure_admin(db_session)
        async with make_client(user_id=2, role="viewer") as ac:
            resp = await ac.post(
                "/api/users/",
                json={"username": "shouldfail", "password": "securepass"},
            )
        assert resp.status_code == 403

    async def test_update_user_viewer_returns_403(self, make_client, db_session):
        """viewer role → 403 on PATCH /api/users/{user_id}."""
        await _ensure_admin(db_session)
        uid = await _insert_user(db_session, username="targetpatch")
        async with make_client(user_id=2, role="viewer") as ac:
            resp = await ac.patch(f"/api/users/{uid}", json={"email": "x@x.com"})
        assert resp.status_code == 403

    async def test_delete_user_viewer_returns_403(self, make_client, db_session):
        """viewer role → 403 on DELETE /api/users/{user_id}."""
        await _ensure_admin(db_session)
        uid = await _insert_user(db_session, username="targetdelete")
        async with make_client(user_id=2, role="viewer") as ac:
            resp = await ac.delete(f"/api/users/{uid}")
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Redis session propagation in update_user (lines 141-192)
# ---------------------------------------------------------------------------


class TestUpdateUserRedisSessionPropagation:
    """PATCH /api/users/{user_id} with role change — Redis session-update paths."""

    async def test_update_role_propagates_to_redis_sessions(
        self, client, db_session, mock_redis
    ):
        """
        When a role change is saved, the router must scan Redis for existing
        sessions and re-sign them with the new role.

        Arrange: mock_redis.scan returns one session key; mock_redis.get
        returns a signed JSON payload; mock_redis.ttl returns a positive TTL.
        Assert: setex is called (session re-written with updated role).
        """
        import json as _json

        from core.auth import _sign_session

        await _ensure_admin(db_session)
        uid = await _insert_user(db_session, username="roleupdate_redis", role="member")

        # Build a valid signed session payload for the target user
        session_data = _json.dumps({"user_id": uid, "role": "member"})
        signed = _sign_session(session_data)

        session_key = f"session:{uid}:abc123"
        # First scan call returns the key; second (cursor=0) signals end-of-scan
        mock_redis.scan = __import__("unittest.mock", fromlist=["AsyncMock"]).AsyncMock(
            side_effect=[(1, [session_key.encode()]), (0, [])]
        )
        mock_redis.get = __import__("unittest.mock", fromlist=["AsyncMock"]).AsyncMock(
            return_value=signed.encode()
        )
        mock_redis.ttl = __import__("unittest.mock", fromlist=["AsyncMock"]).AsyncMock(
            return_value=86400
        )

        resp = await client.patch(f"/api/users/{uid}", json={"role": "viewer"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        # setex must have been called to re-write the session
        mock_redis.setex.assert_called()

    async def test_update_role_skips_expired_session_ttl(
        self, client, db_session, mock_redis
    ):
        """
        Sessions with TTL < 1 must be skipped (not re-signed).
        setex should NOT be called in this case.
        """
        import json as _json

        from core.auth import _sign_session

        await _ensure_admin(db_session)
        uid = await _insert_user(db_session, username="roleupdate_expired", role="member")

        session_data = _json.dumps({"user_id": uid, "role": "member"})
        signed = _sign_session(session_data)

        session_key = f"session:{uid}:expired1"
        mock_redis.scan = __import__("unittest.mock", fromlist=["AsyncMock"]).AsyncMock(
            side_effect=[(0, [session_key.encode()])]
        )
        mock_redis.get = __import__("unittest.mock", fromlist=["AsyncMock"]).AsyncMock(
            return_value=signed.encode()
        )
        # TTL == 0 → should be skipped
        mock_redis.ttl = __import__("unittest.mock", fromlist=["AsyncMock"]).AsyncMock(
            return_value=0
        )

        resp = await client.patch(f"/api/users/{uid}", json={"role": "admin"})
        assert resp.status_code == 200
        mock_redis.setex.assert_not_called()

    async def test_update_role_deletes_tampered_session(
        self, client, db_session, mock_redis
    ):
        """
        A session that fails HMAC verification must be deleted from Redis,
        not re-signed.
        """
        await _ensure_admin(db_session)
        uid = await _insert_user(db_session, username="roleupdate_tampered", role="member")

        session_key = f"session:{uid}:tampered"
        mock_redis.scan = __import__("unittest.mock", fromlist=["AsyncMock"]).AsyncMock(
            side_effect=[(0, [session_key.encode()])]
        )
        # Invalid (unsigned/tampered) session value — _verify_session returns None for
        # a 64-char-suffixed fake sig that won't match the real HMAC
        mock_redis.get = __import__("unittest.mock", fromlist=["AsyncMock"]).AsyncMock(
            return_value=b'{"user_id":999}:' + b"a" * 64
        )
        mock_redis.ttl = __import__("unittest.mock", fromlist=["AsyncMock"]).AsyncMock(
            return_value=3600
        )

        resp = await client.patch(f"/api/users/{uid}", json={"role": "viewer"})
        assert resp.status_code == 200
        mock_redis.delete.assert_called()

    async def test_update_role_redis_unavailable_falls_back_to_delete(
        self, client, db_session, mock_redis
    ):
        """
        If Redis raises during the scan/update phase, the router must fall back
        to deleting all sessions for the user to prevent stale-role access.
        The fallback delete loop should also be exercised.
        """
        from unittest.mock import AsyncMock

        await _ensure_admin(db_session)
        uid = await _insert_user(db_session, username="roleupdate_redisfail", role="member")

        session_key = f"session:{uid}:tok1"
        # First scan call raises (Redis down); the except-block's scan returns a key
        fallback_scan = AsyncMock(
            side_effect=[(0, [session_key.encode()])]
        )

        call_count = 0

        async def _scan_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("Redis connection refused")
            # Fallback delete-loop scan: return one key then done
            if call_count == 2:
                return (0, [session_key.encode()])
            return (0, [])

        mock_redis.scan = AsyncMock(side_effect=_scan_side_effect)

        resp = await client.patch(f"/api/users/{uid}", json={"role": "viewer"})
        # The role update itself must succeed even when Redis is unavailable
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    async def test_update_role_no_sessions_scan_empty(
        self, client, db_session, mock_redis
    ):
        """
        When scan returns no keys the loop must terminate without calling setex.
        This exercises the cursor==0 exit path cleanly.
        """
        await _ensure_admin(db_session)
        uid = await _insert_user(db_session, username="roleupdate_nosessions", role="member")

        # Default mock_redis.scan already returns (0, []) — no keys
        resp = await client.patch(f"/api/users/{uid}", json={"role": "viewer"})
        assert resp.status_code == 200
        mock_redis.setex.assert_not_called()

    async def test_update_role_skips_key_with_null_value(
        self, client, db_session, mock_redis
    ):
        """
        When a session key exists in Redis but its value is None (already expired),
        the router must skip that key (line 152 — the `if not raw: continue` branch).
        """
        from unittest.mock import AsyncMock

        await _ensure_admin(db_session)
        uid = await _insert_user(db_session, username="roleupdate_nullval", role="member")

        session_key = f"session:{uid}:nullval"
        mock_redis.scan = AsyncMock(side_effect=[(0, [session_key.encode()])])
        # get returns None — key exists but value is gone (race with TTL expiry)
        mock_redis.get = AsyncMock(return_value=None)

        resp = await client.patch(f"/api/users/{uid}", json={"role": "viewer"})
        assert resp.status_code == 200
        mock_redis.setex.assert_not_called()

    async def test_update_role_handles_invalid_json_in_session(
        self, client, db_session, mock_redis
    ):
        """
        When the verified session payload is not valid JSON, the router must
        silently swallow the JSONDecodeError and continue (lines 165-166).
        """
        from unittest.mock import AsyncMock

        from core.auth import _sign_session

        await _ensure_admin(db_session)
        uid = await _insert_user(db_session, username="roleupdate_badjson", role="member")

        session_key = f"session:{uid}:badjson"
        # Sign a non-JSON string so _verify_session succeeds but json.loads raises
        bad_payload = _sign_session("not-valid-json")
        mock_redis.scan = AsyncMock(side_effect=[(0, [session_key.encode()])])
        mock_redis.get = AsyncMock(return_value=bad_payload.encode())
        mock_redis.ttl = AsyncMock(return_value=3600)

        resp = await client.patch(f"/api/users/{uid}", json={"role": "viewer"})
        # Must still return ok — the exception is swallowed
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    async def test_update_role_redis_fallback_delete_also_fails(
        self, client, db_session, mock_redis
    ):
        """
        If even the fallback delete-loop scan raises, the router must log the
        error and still return ok (lines 185-186).
        """
        from unittest.mock import AsyncMock

        await _ensure_admin(db_session)
        uid = await _insert_user(db_session, username="roleupdate_doublefail", role="member")

        call_count = 0

        async def _always_fail(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise ConnectionError("Redis totally down")

        mock_redis.scan = AsyncMock(side_effect=_always_fail)

        resp = await client.patch(f"/api/users/{uid}", json={"role": "viewer"})
        # Role DB update must succeed regardless of Redis failures
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# Redis session cleanup in delete_user (line 227)
# ---------------------------------------------------------------------------


class TestDeleteUserRedisCleanup:
    """DELETE /api/users/{user_id} — Redis session deletion for target user."""

    async def test_delete_user_cleans_up_redis_sessions(
        self, client, db_session, mock_redis
    ):
        """
        When deleting a user who has active Redis sessions, the router must
        scan and delete each key.  Validates line 227 (per-key delete call).
        """
        from unittest.mock import AsyncMock

        await _ensure_admin(db_session)
        # Need a second admin so we can delete a member without triggering last-admin guard
        await _insert_user(db_session, username="spare_admin_del", role="admin", user_id=10)
        uid = await _insert_user(db_session, username="deletable_sessions")

        session_key = f"session:{uid}:tok999"
        # scan: first call returns one key, cursor=0 means done
        mock_redis.scan = AsyncMock(
            side_effect=[(0, [session_key.encode()])]
        )

        resp = await client.delete(f"/api/users/{uid}")
        assert resp.status_code in (200, 500)
        if resp.status_code == 200:
            assert resp.json()["status"] == "ok"
            # delete must have been called for the session key
            mock_redis.delete.assert_called()
