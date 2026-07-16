"""Tests for the authenticated image processing enqueue API."""

from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import text


async def _seed_image(db_session, *, owner_id: int = 1) -> None:
    await db_session.execute(
        text(
            "INSERT OR IGNORE INTO users (id, username, password_hash, role) "
            "VALUES (:id, :username, 'x', 'member')"
        ),
        {"id": owner_id, "username": f"user-{owner_id}"},
    )
    await db_session.execute(
        text(
            "INSERT INTO galleries (id, source, source_id, title, pages, visibility, created_by_user_id) "
            "VALUES (9001, 'local', 'process-book', 'Book', 1, 'private', :owner_id)"
        ),
        {"owner_id": owner_id},
    )
    await db_session.execute(
        text(
            "INSERT INTO blobs (sha256, file_size, extension, ref_count) "
            "VALUES ('process-sha', 10, '.png', 1)"
        )
    )
    await db_session.execute(
        text(
            "INSERT INTO images (id, gallery_id, page_num, filename, blob_sha256, visibility) "
            "VALUES (9001, 9001, 1, '001.png', 'process-sha', 'active')"
        )
    )
    await db_session.commit()


async def test_process_image_enqueues_render_job(client, db_session):
    await _seed_image(db_session)
    job = MagicMock(key="process-job")
    enqueue = AsyncMock(return_value=job)

    with (
        patch("routers.process.plugin_registry.get_processor", return_value=MagicMock()),
        patch("core.queue.enqueue", enqueue),
        patch("routers.process.emit_safe", new_callable=AsyncMock),
    ):
        response = await client.post(
            "/api/process/images/9001",
            json={"processor_id": "swarmui", "model": "refiner.safetensors", "scale": 2},
        )

    assert response.status_code == 202
    assert response.json()["job_id"] == "process-job"
    enqueue.assert_awaited_once_with(
        "process_job",
        image_id=9001,
        processor_id="swarmui",
        options={"model": "refiner.safetensors", "scale": 2.0, "tiling": True},
        actor_user_id=1,
        _timeout=1800,
    )


async def test_process_image_applies_gallery_access_filter(make_client, db_session):
    await _seed_image(db_session, owner_id=2)
    await db_session.execute(
        text("INSERT INTO users (id, username, password_hash, role) VALUES (3, 'other', 'x', 'member')")
    )
    await db_session.commit()

    async with make_client(user_id=3, role="member") as member_client:
        response = await member_client.post(
            "/api/process/images/9001",
            json={"processor_id": "swarmui", "scale": 2},
        )

    assert response.status_code == 404


async def test_process_image_requires_auth(unauthed_client):
    response = await unauthed_client.post(
        "/api/process/images/9001",
        json={"processor_id": "swarmui", "scale": 2},
    )
    assert response.status_code == 401


async def _grant_permission(db_session, *, user_id: int, can_edit: bool) -> None:
    await db_session.execute(
        text("INSERT INTO users (id, username, password_hash, role) VALUES (:id, :u, 'x', 'member')"),
        {"id": user_id, "u": f"collab-{user_id}"},
    )
    await db_session.execute(
        text(
            "INSERT INTO gallery_permissions (gallery_id, user_id, can_edit) VALUES (9001, :id, :edit)"
        ),
        {"id": user_id, "edit": 1 if can_edit else 0},
    )
    await db_session.commit()


async def test_process_readonly_collaborator_cannot_process_returns_403(make_client, db_session):
    """A can_edit=false collaborator can view the gallery but must not mutate its images."""
    await _seed_image(db_session, owner_id=2)
    await _grant_permission(db_session, user_id=3, can_edit=False)

    async with make_client(user_id=3, role="member") as reader:
        with (
            patch("routers.process.plugin_registry.get_processor", return_value=MagicMock()),
            patch("core.queue.enqueue", AsyncMock(return_value=MagicMock(key="j"))),
            patch("routers.process.emit_safe", new_callable=AsyncMock),
        ):
            response = await reader.post(
                "/api/process/images/9001",
                json={"processor_id": "swarmui", "scale": 2},
            )

    assert response.status_code == 403


async def test_process_editor_collaborator_can_process(make_client, db_session):
    """A can_edit=true collaborator is allowed to enqueue processing."""
    await _seed_image(db_session, owner_id=2)
    await _grant_permission(db_session, user_id=3, can_edit=True)
    job = MagicMock(key="process-job")

    async with make_client(user_id=3, role="member") as editor:
        with (
            patch("routers.process.plugin_registry.get_processor", return_value=MagicMock()),
            patch("core.queue.enqueue", AsyncMock(return_value=job)),
            patch("routers.process.emit_safe", new_callable=AsyncMock),
        ):
            response = await editor.post(
                "/api/process/images/9001",
                json={"processor_id": "swarmui", "scale": 2},
            )

    assert response.status_code == 202
