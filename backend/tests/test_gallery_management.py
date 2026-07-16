"""Regression tests for gallery collaboration endpoints."""

from sqlalchemy import text


async def _seed_galleries(db_session) -> None:
    await db_session.execute(
        text(
            "INSERT OR IGNORE INTO users (id, username, password_hash, role) VALUES "
            "(1, 'owner', 'x', 'admin'), (2, 'reader', 'x', 'member')"
        )
    )
    await db_session.execute(
        text(
            "INSERT INTO galleries (id, source, source_id, title, pages, tags_array, created_by_user_id) VALUES "
            "(9101, 'local', 'first', 'First', 1, '[\"general:one\"]', 1), "
            "(9102, 'local', 'second', 'Second', 1, '[\"general:two\"]', 1)"
        )
    )
    await db_session.execute(
        text(
            "INSERT INTO blobs (sha256, file_size, media_type, extension, storage, ref_count) VALUES "
            "('aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', 1, 'image', '.jpg', 'cas', 1), "
            "('bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', 1, 'image', '.jpg', 'cas', 1)"
        )
    )
    await db_session.execute(
        text(
            "INSERT INTO images (id, gallery_id, page_num, filename, blob_sha256) VALUES "
            "(9201, 9101, 1, 'one.jpg', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'), "
            "(9202, 9102, 1, 'two.jpg', 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb')"
        )
    )
    await db_session.commit()


async def test_visibility_permissions_and_expiring_share(client, db_session):
    await _seed_galleries(db_session)
    updated = await client.patch(
        "/api/gallery-management/galleries/9101/sharing",
        json={"visibility": "private", "permissions": [{"user_id": 2, "can_edit": True}]},
    )
    created = await client.post(
        "/api/gallery-management/galleries/9101/shares",
        json={"expires_in_hours": 24, "filter_r18": True},
    )
    token = created.json()["token"]
    public = await client.get(f"/api/gallery-management/shares/{token}")
    sharing = await client.get("/api/gallery-management/galleries/9101/sharing")

    assert updated.status_code == 200, updated.text
    assert created.status_code == 201, created.text
    assert public.status_code == 200, public.text
    assert public.json()["images"][0]["id"] == 9201
    assert sharing.json()["permissions"] == [{"user_id": 2, "username": "reader", "can_edit": True}]


async def test_r18_filter_blocks_shared_gallery(client, db_session):
    await _seed_galleries(db_session)
    await db_session.execute(text("UPDATE galleries SET tags_array='[\"rating:explicit\"]' WHERE id=9101"))
    await db_session.commit()
    created = await client.post(
        "/api/gallery-management/galleries/9101/shares",
        json={"expires_in_hours": 24, "filter_r18": True},
    )
    response = await client.get(f"/api/gallery-management/shares/{created.json()['token']}")
    assert response.status_code == 451


async def test_link_versions_and_merge_preserves_user_state(client, db_session):
    await _seed_galleries(db_session)
    await db_session.execute(text("INSERT INTO user_favorites (user_id, gallery_id) VALUES (2, 9102)"))
    await db_session.execute(text("INSERT INTO user_ratings (user_id, gallery_id, rating) VALUES (2, 9102, 4)"))
    await db_session.execute(
        text("INSERT INTO read_progress (user_id, gallery_id, last_page, last_image_id) VALUES (2, 9102, 1, 9202)")
    )
    await db_session.commit()

    linked = await client.post("/api/gallery-management/galleries/9101/versions", json={"gallery_id": 9102})
    versions = await client.get("/api/gallery-management/galleries/9101/versions")
    merged = await client.post("/api/gallery-management/galleries/9101/merge", json={"source_gallery_id": 9102})

    assert linked.status_code == 200, linked.text
    assert len(versions.json()["versions"]) == 2
    assert merged.status_code == 200, merged.text
    assert merged.json()["pages"] == 2
    image_page = (await db_session.execute(text("SELECT page_num FROM images WHERE id=9202"))).scalar_one()
    favorite = (
        await db_session.execute(text("SELECT count(*) FROM user_favorites WHERE user_id=2 AND gallery_id=9101"))
    ).scalar_one()
    rating = (
        await db_session.execute(text("SELECT rating FROM user_ratings WHERE user_id=2 AND gallery_id=9101"))
    ).scalar_one()
    progress = (
        await db_session.execute(text("SELECT last_page FROM read_progress WHERE user_id=2 AND gallery_id=9101"))
    ).scalar_one()
    assert image_page == 2
    assert favorite == 1
    assert rating == 4
    assert progress == 2


async def test_gallery_management_requires_auth(unauthed_client):
    response = await unauthed_client.get("/api/gallery-management/galleries/1/sharing")
    assert response.status_code == 401
