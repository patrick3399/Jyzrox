"""Tests for subscription group router endpoints (/api/subscription-groups/*)."""

from sqlalchemy import text

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _ensure_user(db_session, user_id: int = 1) -> None:
    """Insert the user row if not already present."""
    await db_session.execute(
        text("INSERT OR IGNORE INTO users (id, username, password_hash, role) VALUES (:id, :u, 'x', 'admin')"),
        {"id": user_id, "u": f"grp_user_{user_id}"},
    )
    await db_session.commit()


async def _insert_group(
    db_session,
    name: str = "Test Group",
    schedule: str = "0 */6 * * *",
    concurrency: int = 2,
    priority: int = 5,
    is_system: bool = False,
    status: str = "idle",
) -> int:
    """Insert a subscription_group directly via raw SQL and return its id."""
    result = await db_session.execute(
        text(
            "INSERT INTO subscription_groups "
            "(name, schedule, concurrency, priority, is_system, status) "
            "VALUES (:name, :schedule, :concurrency, :priority, :is_system, :status) "
            "RETURNING id"
        ),
        {
            "name": name,
            "schedule": schedule,
            "concurrency": concurrency,
            "priority": priority,
            "is_system": 1 if is_system else 0,
            "status": status,
        },
    )
    await db_session.commit()
    return result.scalar_one()


async def _insert_subscription(
    db_session,
    user_id: int = 1,
    url: str = "https://example.com/sub/1",
    group_id: int | None = None,
) -> int:
    """Insert a subscription row and return its id."""
    result = await db_session.execute(
        text(
            "INSERT INTO subscriptions (user_id, url, name, source, enabled, auto_download, cron_expr, group_id) "
            "VALUES (:uid, :url, 'Test Sub', 'gallery_dl', 1, 1, '0 */2 * * *', :gid) RETURNING id"
        ),
        {"uid": user_id, "url": url, "gid": group_id},
    )
    await db_session.commit()
    return result.scalar_one()


# ---------------------------------------------------------------------------
# GET /api/subscription-groups/
# ---------------------------------------------------------------------------


class TestListGroups:
    """GET /api/subscription-groups/ — list all subscription groups."""

    async def test_list_groups_empty_returns_empty_list(self, client, db_session):
        """No groups → groups is an empty list."""
        await _ensure_user(db_session)
        resp = await client.get("/api/subscription-groups/")
        assert resp.status_code == 200
        data = resp.json()
        assert "groups" in data
        assert isinstance(data["groups"], list)

    async def test_list_groups_returns_inserted_group(self, client, db_session):
        """A group inserted directly appears in the listing."""
        await _ensure_user(db_session)
        await _insert_group(db_session, name="Visible Group")

        resp = await client.get("/api/subscription-groups/")
        assert resp.status_code == 200
        names = [g["name"] for g in resp.json()["groups"]]
        assert "Visible Group" in names

    async def test_list_groups_response_shape(self, client, db_session):
        """Each group entry must include all expected fields."""
        await _ensure_user(db_session)
        await _insert_group(db_session, name="Shape Group")

        resp = await client.get("/api/subscription-groups/")
        assert resp.status_code == 200
        group = resp.json()["groups"][0]
        for field in (
            "id",
            "name",
            "schedule",
            "concurrency",
            "enabled",
            "priority",
            "is_system",
            "status",
            "sub_count",
        ):
            assert field in group, f"Missing field: {field}"

    async def test_list_groups_sub_count_reflects_linked_subscriptions(self, client, db_session):
        """sub_count must equal the number of subscriptions assigned to the group."""
        await _ensure_user(db_session)
        group_id = await _insert_group(db_session, name="Count Group")
        await _insert_subscription(db_session, url="https://example.com/a1", group_id=group_id)
        await _insert_subscription(db_session, url="https://example.com/a2", group_id=group_id)

        resp = await client.get("/api/subscription-groups/")
        assert resp.status_code == 200
        target = [g for g in resp.json()["groups"] if g["id"] == group_id]
        assert len(target) == 1
        assert target[0]["sub_count"] == 2

    async def test_list_groups_sub_count_zero_when_no_subs(self, client, db_session):
        """sub_count is 0 for a group with no subscriptions."""
        await _ensure_user(db_session)
        group_id = await _insert_group(db_session, name="Empty Count Group")

        resp = await client.get("/api/subscription-groups/")
        assert resp.status_code == 200
        target = [g for g in resp.json()["groups"] if g["id"] == group_id]
        assert len(target) == 1
        assert target[0]["sub_count"] == 0


# ---------------------------------------------------------------------------
# POST /api/subscription-groups/
# ---------------------------------------------------------------------------


class TestCreateGroup:
    """POST /api/subscription-groups/ — create a new subscription group."""

    async def test_create_group_returns_ok_with_id(self, client, db_session):
        """Valid payload → 200 with status=ok and a numeric id."""
        await _ensure_user(db_session)
        resp = await client.post(
            "/api/subscription-groups/",
            json={
                "name": "New Group",
                "schedule": "0 */4 * * *",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert isinstance(data["id"], int)

    async def test_create_group_with_custom_concurrency_and_priority(self, client, db_session):
        """concurrency and priority fields are accepted."""
        await _ensure_user(db_session)
        resp = await client.post(
            "/api/subscription-groups/",
            json={
                "name": "Custom Group",
                "schedule": "0 */6 * * *",
                "concurrency": 4,
                "priority": 8,
            },
        )
        assert resp.status_code == 200
        assert "id" in resp.json()

    async def test_create_group_invalid_cron_returns_400(self, client, db_session):
        """An invalid cron expression → 400 before DB insert."""
        await _ensure_user(db_session)
        resp = await client.post(
            "/api/subscription-groups/",
            json={
                "name": "Bad Cron Group",
                "schedule": "not a cron",
            },
        )
        assert resp.status_code == 400

    async def test_create_group_missing_name_returns_422(self, client, db_session):
        """Missing required name field → 422 from Pydantic."""
        await _ensure_user(db_session)
        resp = await client.post(
            "/api/subscription-groups/",
            json={
                "schedule": "0 */6 * * *",
            },
        )
        assert resp.status_code == 422

    async def test_create_group_default_schedule_accepted(self, client, db_session):
        """Name-only payload uses the default schedule."""
        await _ensure_user(db_session)
        resp = await client.post(
            "/api/subscription-groups/",
            json={
                "name": "Default Schedule Group",
            },
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# GET /api/subscription-groups/{group_id}
# ---------------------------------------------------------------------------


class TestGetGroup:
    """GET /api/subscription-groups/{group_id} — retrieve a single group."""

    async def test_get_group_returns_correct_fields(self, client, db_session):
        """Group detail includes id, name, schedule, sub_count, etc."""
        await _ensure_user(db_session)
        group_id = await _insert_group(db_session, name="Detail Group", schedule="0 3 * * *")

        resp = await client.get(f"/api/subscription-groups/{group_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == group_id
        assert data["name"] == "Detail Group"
        assert data["schedule"] == "0 3 * * *"
        assert "sub_count" in data

    async def test_get_group_sub_count_is_zero_when_no_subs(self, client, db_session):
        """sub_count is 0 for a newly created group with no subscriptions."""
        await _ensure_user(db_session)
        group_id = await _insert_group(db_session)

        resp = await client.get(f"/api/subscription-groups/{group_id}")
        assert resp.status_code == 200
        assert resp.json()["sub_count"] == 0

    async def test_get_nonexistent_group_returns_404(self, client, db_session):
        """GET on a non-existent group_id → 404."""
        await _ensure_user(db_session)
        resp = await client.get("/api/subscription-groups/99999")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /api/subscription-groups/{group_id}
# ---------------------------------------------------------------------------


class TestUpdateGroup:
    """PATCH /api/subscription-groups/{group_id} — update a group."""

    async def test_update_group_name_returns_ok(self, client, db_session):
        """Patching name → 200 with status=ok."""
        await _ensure_user(db_session)
        group_id = await _insert_group(db_session, name="Old Name")

        resp = await client.patch(f"/api/subscription-groups/{group_id}", json={"name": "New Name"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    async def test_update_group_name_reflected_on_get(self, client, db_session):
        """After patching name, GET returns the updated name."""
        await _ensure_user(db_session)
        group_id = await _insert_group(db_session, name="Before Update")

        await client.patch(f"/api/subscription-groups/{group_id}", json={"name": "After Update"})

        resp = await client.get(f"/api/subscription-groups/{group_id}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "After Update"

    async def test_update_group_schedule_reflected_on_get(self, client, db_session):
        """After patching schedule, GET returns the new schedule."""
        await _ensure_user(db_session)
        group_id = await _insert_group(db_session, schedule="0 */6 * * *")

        await client.patch(f"/api/subscription-groups/{group_id}", json={"schedule": "0 */12 * * *"})

        resp = await client.get(f"/api/subscription-groups/{group_id}")
        assert resp.status_code == 200
        assert resp.json()["schedule"] == "0 */12 * * *"

    async def test_update_group_invalid_cron_returns_400(self, client, db_session):
        """Patching with an invalid cron expression → 400."""
        await _ensure_user(db_session)
        group_id = await _insert_group(db_session)

        resp = await client.patch(f"/api/subscription-groups/{group_id}", json={"schedule": "bad cron"})
        assert resp.status_code == 400

    async def test_update_group_no_fields_returns_400(self, client, db_session):
        """Empty patch body → 400 (no fields to update)."""
        await _ensure_user(db_session)
        group_id = await _insert_group(db_session)

        resp = await client.patch(f"/api/subscription-groups/{group_id}", json={})
        assert resp.status_code == 400

    async def test_update_nonexistent_group_returns_404(self, client, db_session):
        """PATCH on a non-existent group_id → 404."""
        await _ensure_user(db_session)

        resp = await client.patch("/api/subscription-groups/99999", json={"name": "Ghost"})
        assert resp.status_code == 404

    async def test_update_group_enabled_false_returns_ok(self, client, db_session):
        """Patching enabled=False → 200."""
        await _ensure_user(db_session)
        group_id = await _insert_group(db_session)

        resp = await client.patch(f"/api/subscription-groups/{group_id}", json={"enabled": False})
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# DELETE /api/subscription-groups/{group_id}
# ---------------------------------------------------------------------------


class TestDeleteGroup:
    """DELETE /api/subscription-groups/{group_id} — delete a group."""

    async def test_delete_group_returns_ok(self, client, db_session):
        """Deleting an existing non-system group → 200 with status=ok."""
        await _ensure_user(db_session)
        group_id = await _insert_group(db_session, name="To Delete")

        resp = await client.delete(f"/api/subscription-groups/{group_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    async def test_delete_group_then_absent_on_get(self, client, db_session):
        """After deletion, GET on the same id → 404."""
        await _ensure_user(db_session)
        group_id = await _insert_group(db_session, name="Gone Group")

        await client.delete(f"/api/subscription-groups/{group_id}")

        resp = await client.get(f"/api/subscription-groups/{group_id}")
        assert resp.status_code == 404

    async def test_delete_nonexistent_group_returns_404(self, client, db_session):
        """Deleting a non-existent group_id → 404."""
        await _ensure_user(db_session)
        resp = await client.delete("/api/subscription-groups/99999")
        assert resp.status_code == 404

    async def test_delete_system_group_returns_400(self, client, db_session):
        """System groups cannot be deleted — returns 400."""
        await _ensure_user(db_session)
        group_id = await _insert_group(db_session, name="System Group", is_system=True)

        resp = await client.delete(f"/api/subscription-groups/{group_id}")
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# POST /api/subscription-groups/{group_id}/pause
# POST /api/subscription-groups/{group_id}/resume
# ---------------------------------------------------------------------------


class TestPauseResumeGroup:
    """Pause and resume a subscription group."""

    async def test_pause_group_returns_ok(self, client, db_session):
        """Pausing a group → 200 with status=ok."""
        await _ensure_user(db_session)
        group_id = await _insert_group(db_session)

        resp = await client.post(f"/api/subscription-groups/{group_id}/pause")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    async def test_pause_group_reflected_in_status(self, client, db_session):
        """After pausing, GET returns status=paused."""
        await _ensure_user(db_session)
        group_id = await _insert_group(db_session, status="idle")

        await client.post(f"/api/subscription-groups/{group_id}/pause")

        resp = await client.get(f"/api/subscription-groups/{group_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "paused"

    async def test_resume_group_returns_ok(self, client, db_session):
        """Resuming a paused group → 200 with status=ok."""
        await _ensure_user(db_session)
        group_id = await _insert_group(db_session, status="paused")

        resp = await client.post(f"/api/subscription-groups/{group_id}/resume")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    async def test_resume_group_reflected_in_status(self, client, db_session):
        """After resuming, GET returns status=idle."""
        await _ensure_user(db_session)
        group_id = await _insert_group(db_session, status="paused")

        await client.post(f"/api/subscription-groups/{group_id}/resume")

        resp = await client.get(f"/api/subscription-groups/{group_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "idle"

    async def test_pause_then_resume_round_trip(self, client, db_session):
        """Full pause → resume cycle ends with status=idle."""
        await _ensure_user(db_session)
        group_id = await _insert_group(db_session, status="idle")

        await client.post(f"/api/subscription-groups/{group_id}/pause")
        await client.post(f"/api/subscription-groups/{group_id}/resume")

        resp = await client.get(f"/api/subscription-groups/{group_id}")
        assert resp.json()["status"] == "idle"

    async def test_resume_non_paused_group_returns_404(self, client, db_session):
        """Resuming a group that is not paused → 404 (WHERE status='paused' matches nothing)."""
        await _ensure_user(db_session)
        group_id = await _insert_group(db_session, status="idle")

        resp = await client.post(f"/api/subscription-groups/{group_id}/resume")
        assert resp.status_code == 404

    async def test_pause_nonexistent_group_returns_404(self, client, db_session):
        """Pausing a non-existent group_id → 404."""
        await _ensure_user(db_session)
        resp = await client.post("/api/subscription-groups/99999/pause")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/subscription-groups/{group_id}/run
# ---------------------------------------------------------------------------


class TestRunGroup:
    """POST /api/subscription-groups/{group_id}/run — Run Now."""

    async def test_run_group_enqueues_job_and_returns_queued(self, client, db_session):
        """Run Now → 200 with status=queued and the group_id."""
        await _ensure_user(db_session)
        group_id = await _insert_group(db_session)

        resp = await client.post(f"/api/subscription-groups/{group_id}/run")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "queued"
        assert data["group_id"] == group_id

    async def test_run_nonexistent_group_returns_404(self, client, db_session):
        """Run Now on a non-existent group_id → 404."""
        await _ensure_user(db_session)
        resp = await client.post("/api/subscription-groups/99999/run")
        assert resp.status_code == 404
