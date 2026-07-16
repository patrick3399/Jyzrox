"""Regression tests for reading event collection and statistics."""

from sqlalchemy import text


async def _seed_reading_gallery(db_session):
    await db_session.execute(
        text("INSERT OR IGNORE INTO users (id, username, password_hash, role) VALUES (1, 'reader', 'x', 'admin')")
    )
    await db_session.execute(
        text(
            "INSERT INTO galleries (id, source, source_id, title, pages) VALUES (9601, 'local', 'reading', 'Reading', 3)"
        )
    )
    for page, char in enumerate(("d", "e", "f"), start=1):
        sha = char * 64
        await db_session.execute(
            text(
                "INSERT INTO blobs (sha256, file_size, media_type, extension, storage, ref_count) VALUES (:sha, 1, 'image', '.jpg', 'cas', 1)"
            ),
            {"sha": sha},
        )
        await db_session.execute(
            text("INSERT INTO images (id, gallery_id, page_num, blob_sha256) VALUES (:id, 9601, :page, :sha)"),
            {"id": 9601 + page, "page": page, "sha": sha},
        )
    await db_session.execute(text("INSERT INTO tags (id, namespace, name) VALUES (9610, 'artist', 'reader')"))
    await db_session.execute(
        text("INSERT INTO gallery_tags (gallery_id, tag_id, confidence, source) VALUES (9601, 9610, 1, 'metadata')")
    )
    await db_session.commit()


async def test_progress_change_records_event_and_stats(client, db_session):
    await _seed_reading_gallery(db_session)
    saved = await client.post("/api/library/galleries/local/reading/progress", json={"last_page": 2})
    stats = await client.get("/api/library/stats?days=30")
    assert saved.status_code == 200, saved.text
    assert stats.status_code == 200, stats.text
    assert stats.json()["trend"][0]["events"] == 1
    assert stats.json()["top_tags"][0]["name"] == "reader"
    assert stats.json()["unfinished"][0]["last_page"] == 2


async def test_explicit_read_event_requires_gallery_access(client, db_session):
    await _seed_reading_gallery(db_session)
    response = await client.post(
        "/api/library/read-events",
        json={"gallery_id": 9601, "page_num": 1, "duration_ms": 1500},
    )
    assert response.status_code == 201
    duration = (await db_session.execute(text("SELECT duration_ms FROM read_events"))).scalar_one()
    assert duration == 1500


async def test_read_events_require_auth(unauthed_client):
    response = await unauthed_client.post("/api/library/read-events", json={"gallery_id": 1, "page_num": 1})
    assert response.status_code == 401
