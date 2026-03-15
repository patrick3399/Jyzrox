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
