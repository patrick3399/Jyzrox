"""Tests for AI-versus-metadata tag anomaly suggestions."""

from sqlalchemy import text


async def test_tag_anomalies_compare_image_ai_and_gallery_metadata(client, db_session):
    await db_session.execute(
        text("INSERT OR IGNORE INTO users (id, username, password_hash, role) VALUES (1, 'admin', 'x', 'admin')")
    )
    await db_session.execute(
        text("INSERT INTO galleries (id, source, source_id, title) VALUES (9501, 'local', 'anomaly', 'Anomaly')")
    )
    await db_session.execute(
        text(
            "INSERT INTO blobs (sha256, file_size, media_type, extension, storage, ref_count) VALUES "
            "('cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc', 1, 'image', '.jpg', 'cas', 1)"
        )
    )
    await db_session.execute(
        text(
            "INSERT INTO images (id, gallery_id, page_num, blob_sha256) VALUES "
            "(9502, 9501, 1, 'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc')"
        )
    )
    await db_session.execute(
        text(
            "INSERT INTO tags (id, namespace, name) VALUES "
            "(9503, 'general', 'metadata-only'), (9504, 'general', 'ai-only')"
        )
    )
    await db_session.execute(
        text("INSERT INTO gallery_tags (gallery_id, tag_id, confidence, source) VALUES (9501, 9503, 1.0, 'metadata')")
    )
    await db_session.execute(text("INSERT INTO image_tags (image_id, tag_id, confidence) VALUES (9502, 9504, 0.95)"))
    await db_session.commit()

    response = await client.get("/api/tags/anomalies?min_difference=0.8")
    assert response.status_code == 200, response.text
    suggestions = {item["suggestion"] for item in response.json()["anomalies"]}
    assert suggestions == {"review_ai_only", "review_metadata_only"}


async def test_tag_anomalies_require_admin(unauthed_client):
    assert (await unauthed_client.get("/api/tags/anomalies")).status_code == 401
