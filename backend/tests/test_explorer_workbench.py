"""Regression coverage for Library Workbench metadata provenance."""

from unittest.mock import AsyncMock, patch

from sqlalchemy import select, text

from db.models import (
    Blob,
    CollectionGallery,
    Gallery,
    GalleryMetadataChange,
    GalleryMetadataFieldState,
    GalleryTag,
    Image,
    ReadProgress,
    UserFavorite,
    UserRating,
    WorkbenchOperation,
)
from services.workbench_metadata import apply_source_scalar_metadata


async def _seed_user_and_galleries(db_session) -> None:
    await db_session.execute(
        text(
            "INSERT INTO users (id, username, password_hash, role) "
            "VALUES (1, 'admin', 'unused', 'admin')"
        )
    )
    await db_session.execute(
        text(
            "INSERT INTO galleries "
            "(id, source, source_id, title, category, visibility, created_by_user_id) VALUES "
            "(101, 'local', 'one', 'Old one', 'Manga', 'public', 1), "
            "(102, 'local', 'two', 'Old two', 'Manga', 'public', 1)"
        )
    )
    await db_session.commit()


async def test_bulk_metadata_records_locked_provenance_and_operation(client, db_session):
    await _seed_user_and_galleries(db_session)

    response = await client.post(
        "/api/explorer/operations/metadata",
        json={
            "gallery_ids": [101, 102],
            "fields": {
                "title": {"mode": "set", "value": "Unified title"},
                "category": {"mode": "clear"},
                "language": {"mode": "keep"},
            },
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["selection_count"] == 2
    assert payload["changed_fields"] == 4

    galleries = (
        (await db_session.execute(select(Gallery).where(Gallery.id.in_([101, 102])).order_by(Gallery.id)))
        .scalars()
        .all()
    )
    assert [(gallery.title, gallery.category) for gallery in galleries] == [
        ("Unified title", None),
        ("Unified title", None),
    ]
    states = (
        (
            await db_session.execute(
                select(GalleryMetadataFieldState).order_by(
                    GalleryMetadataFieldState.gallery_id,
                    GalleryMetadataFieldState.field_name,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(states) == 4
    assert all(state.origin == "manual" and state.locked for state in states)
    assert {state.source_value for state in states if state.field_name == "title"} == {"Old one", "Old two"}
    assert (await db_session.execute(select(WorkbenchOperation))).scalar_one().status == "completed"


async def test_locked_field_keeps_manual_value_and_exposes_source_diff(client, db_session):
    await _seed_user_and_galleries(db_session)
    response = await client.post(
        "/api/explorer/operations/metadata",
        json={
            "gallery_ids": [101],
            "fields": {"title": {"mode": "set", "value": "Manual title"}},
        },
    )
    assert response.status_code == 200, response.text

    gallery = await db_session.get(Gallery, 101)
    changed, pending = await apply_source_scalar_metadata(db_session, gallery, {"title": "New source title"})
    await db_session.commit()

    assert changed == []
    assert pending == {"title": {"current": "Manual title", "source": "New source title"}}
    assert gallery.title == "Manual title"
    state = await db_session.get(GalleryMetadataFieldState, (101, "title"))
    assert state.locked is True
    assert state.source_value == "New source title"

    history = await client.get("/api/explorer/galleries/101/metadata-history")
    assert history.status_code == 200, history.text
    assert history.json()["fields"]["title"]["source_value"] == "New source title"
    assert history.json()["changes"][0]["new_value"] == "Manual title"


async def test_unlocked_source_refresh_appends_history(db_session):
    await _seed_user_and_galleries(db_session)
    gallery = await db_session.get(Gallery, 101)

    changed, pending = await apply_source_scalar_metadata(db_session, gallery, {"title": "Source title"})
    await db_session.commit()

    assert changed == ["title"]
    assert pending == {}
    assert gallery.title == "Source title"
    change = (await db_session.execute(select(GalleryMetadataChange))).scalar_one()
    assert (change.old_value, change.new_value, change.origin) == ("Old one", "Source title", "source")


async def test_bulk_metadata_rejects_readonly_source_fields(client, db_session):
    await _seed_user_and_galleries(db_session)

    response = await client.post(
        "/api/explorer/operations/metadata",
        json={"gallery_ids": [101], "fields": {"pages": {"mode": "set", "value": 99}}},
    )

    assert response.status_code == 400
    assert "Unsupported metadata fields" in response.json()["detail"]


async def test_merge_copies_references_trashes_sources_and_old_route_is_404(client, db_session):
    await _seed_user_and_galleries(db_session)
    await db_session.execute(
        text(
            "INSERT INTO blobs (sha256, file_size, extension, ref_count, phash_int) VALUES "
            "('sha-a', 100, 'jpg', 2, 0), ('sha-b', 200, 'jpg', 1, 1)"
        )
    )
    await db_session.execute(
        text(
            "INSERT INTO gallery_source_items (id, gallery_id, source_item_id, title) "
            "VALUES (501, 102, 'chapter-1', 'Chapter one')"
        )
    )
    await db_session.execute(
        text(
            "INSERT INTO images (id, gallery_id, page_num, filename, blob_sha256, source_item_row_id) VALUES "
            "(201, 101, 1, 'target.jpg', 'sha-a', NULL), "
            "(202, 102, 1, 'duplicate.jpg', 'sha-a', 501), "
            "(203, 102, 2, 'new.jpg', 'sha-b', 501)"
        )
    )
    await db_session.execute(text("INSERT INTO tags (id, namespace, name) VALUES (301, 'artist', 'test')"))
    await db_session.execute(
        text("INSERT INTO gallery_tags (gallery_id, tag_id, confidence, source) VALUES (102, 301, 0.8, 'metadata')")
    )
    await db_session.execute(
        text("INSERT INTO collections (id, user_id, name) VALUES (401, 1, 'Merged collection')")
    )
    await db_session.execute(
        text("INSERT INTO collection_galleries (collection_id, gallery_id, position) VALUES (401, 102, 0)")
    )
    await db_session.execute(text("INSERT INTO user_favorites (user_id, gallery_id) VALUES (1, 102)"))
    await db_session.execute(text("INSERT INTO user_ratings (user_id, gallery_id, rating) VALUES (1, 102, 8)"))
    await db_session.execute(
        text(
            "INSERT INTO read_progress (user_id, gallery_id, last_page, last_image_id) "
            "VALUES (1, 102, 2, 203)"
        )
    )
    await db_session.commit()

    preview = await client.post(
        "/api/explorer/merge/preview",
        json={"gallery_ids": [101, 102], "target_id": 101},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["images"] == {
        "add": 1,
        "exact_sha_skipped": 1,
        "similar_kept_for_review": 1,
    }
    assert preview.json()["result"]["source_routes"] == "404"

    with patch("core.audit.log_audit", new_callable=AsyncMock):
        response = await client.post(
            "/api/explorer/merge",
            json={
                "gallery_ids": [101, 102],
                "target_id": 101,
                "scalar_sources": {"title": 102},
            },
        )
    assert response.status_code == 200, response.text
    assert response.json()["source_routes"] == "404"
    assert response.json()["images_added"] == 1
    assert response.json()["exact_sha_skipped"] == 1

    target = await db_session.get(Gallery, 101)
    source = await db_session.get(Gallery, 102)
    assert target.title == "Old two"
    assert target.pages == 2
    assert source.deleted_at is not None
    assert len((await db_session.execute(select(Image).where(Image.gallery_id == 102))).scalars().all()) == 2
    target_images = (
        (await db_session.execute(select(Image).where(Image.gallery_id == 101).order_by(Image.page_num)))
        .scalars()
        .all()
    )
    assert [image.blob_sha256 for image in target_images] == ["sha-a", "sha-b"]
    assert (await db_session.get(Blob, "sha-b")).ref_count == 2
    assert await db_session.get(CollectionGallery, (401, 101)) is not None
    assert await db_session.get(UserFavorite, (1, 101)) is not None
    assert (await db_session.get(UserRating, (1, 101))).rating == 8
    assert await db_session.get(GalleryTag, (101, 301)) is not None
    progress = await db_session.get(ReadProgress, (1, 101))
    assert progress.last_page == 2
    assert progress.last_image_id == target_images[1].id

    old_route = await client.get("/api/library/galleries/local/two")
    assert old_route.status_code == 404


async def test_physical_tree_lists_raw_media_without_exposing_host_paths(client, db_session, tmp_path):
    root = tmp_path / "library"
    folder = root / "Artist" / "Gallery"
    folder.mkdir(parents=True)
    image = folder / "cover.jpg"
    image.write_bytes(b"\xff\xd8\xff\xe0" + b"raw-preview")
    await db_session.execute(
        text(
            "INSERT INTO library_paths (id, path, label, pattern, import_mode, enabled, monitor) "
            "VALUES (11, :path, 'Test library', '{artist}/{title}', 'link', 1, 0)"
        ),
        {"path": str(root)},
    )
    await db_session.commit()

    listing = await client.get("/api/explorer/physical/11/entries", params={"path": "Artist/Gallery"})
    assert listing.status_code == 200, listing.text
    payload = listing.json()
    assert payload["read_only"] is True
    assert payload["entries"][0]["path"] == "Artist/Gallery/cover.jpg"
    assert str(root) not in listing.text

    preview = await client.get(
        "/api/explorer/physical/11/preview",
        params={"path": "Artist/Gallery/cover.jpg"},
    )
    assert preview.status_code == 200
    assert preview.headers["content-type"].startswith("image/jpeg")
    assert preview.content.startswith(b"\xff\xd8\xff")


async def test_physical_tree_rejects_traversal_and_symlink_escape(client, db_session, tmp_path):
    root = tmp_path / "library"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "escape").symlink_to(outside, target_is_directory=True)
    await db_session.execute(
        text(
            "INSERT INTO library_paths (id, path, label, pattern, import_mode, enabled, monitor) "
            "VALUES (12, :path, 'Test library', '{title}', 'link', 1, 0)"
        ),
        {"path": str(root)},
    )
    await db_session.commit()

    traversal = await client.get("/api/explorer/physical/12/entries", params={"path": "../outside"})
    assert traversal.status_code == 400
    escaped = await client.get("/api/explorer/physical/12/entries", params={"path": "escape"})
    assert escaped.status_code == 403


async def test_roots_report_logical_and_unique_sizes(client, db_session):
    await _seed_user_and_galleries(db_session)
    await db_session.execute(
        text("INSERT INTO blobs (sha256, file_size, extension, ref_count) VALUES ('shared', 123, 'jpg', 2)")
    )
    await db_session.execute(
        text(
            "INSERT INTO images (gallery_id, page_num, filename, blob_sha256) VALUES "
            "(101, 1, 'one.jpg', 'shared'), (102, 1, 'two.jpg', 'shared')"
        )
    )
    await db_session.commit()

    response = await client.get("/api/explorer/roots")
    assert response.status_code == 200, response.text
    local = next(source for source in response.json()["virtual"]["sources"] if source["id"] == "local")
    assert local["gallery_count"] == 2
    assert local["logical_bytes"] == 246
    assert local["unique_cas_bytes"] == 123


async def test_query_all_selection_can_exclude_items_before_bulk_edit(client, db_session, mock_redis):
    await _seed_user_and_galleries(db_session)
    redis_values: dict[str, str] = {}

    async def remember_setex(key, _ttl, value):
        redis_values[key] = value
        return True

    async def remember_get(key):
        return redis_values.get(key)

    mock_redis.setex.side_effect = remember_setex
    mock_redis.get.side_effect = remember_get

    selection = await client.post(
        "/api/explorer/selections",
        json={"query": {"node_kind": "source", "node_id": "local"}},
    )
    assert selection.status_code == 201, selection.text
    assert selection.json()["count"] == 2

    edited = await client.post(
        "/api/explorer/operations/metadata",
        json={
            "selection_token": selection.json()["selection_token"],
            "excluded_ids": [102],
            "fields": {"language": {"mode": "set", "value": "English"}},
        },
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["selection_count"] == 1
    assert (await db_session.get(Gallery, 101)).language == "English"
    assert (await db_session.get(Gallery, 102)).language is None

    query = await client.post(
        "/api/explorer/query",
        json={"node_kind": "source", "node_id": "local", "sort": "title", "direction": "asc"},
    )
    assert query.status_code == 200, query.text
    assert [item["id"] for item in query.json()["items"]] == [101, 102]


async def test_bulk_actions_manage_personal_state_collections_and_manual_tags(client, db_session):
    await _seed_user_and_galleries(db_session)
    await db_session.execute(text("INSERT INTO collections (id, user_id, name) VALUES (901, 1, 'Workbench')"))
    await db_session.commit()

    favorite = await client.post(
        "/api/explorer/operations/action",
        json={"gallery_ids": [101, 102], "action": "favorite"},
    )
    assert favorite.status_code == 200, favorite.text
    assert favorite.json()["affected"] == 2

    collection = await client.post(
        "/api/explorer/operations/action",
        json={"gallery_ids": [101, 102], "action": "add_collection", "collection_id": 901},
    )
    assert collection.status_code == 200, collection.text
    assert collection.json()["affected"] == 2

    tags = await client.post(
        "/api/explorer/operations/action",
        json={"gallery_ids": [101, 102], "action": "add_tags", "tags": ["artist:workbench"]},
    )
    assert tags.status_code == 200, tags.text
    assert tags.json()["affected"] == 2

    favorites = (
        await db_session.execute(select(UserFavorite).where(UserFavorite.gallery_id.in_([101, 102])))
    ).scalars().all()
    memberships = (
        await db_session.execute(select(CollectionGallery).where(CollectionGallery.collection_id == 901))
    ).scalars().all()
    manual_tags = (
        await db_session.execute(select(GalleryTag).where(GalleryTag.gallery_id.in_([101, 102])))
    ).scalars().all()
    assert len(favorites) == 2
    assert len(memberships) == 2
    assert len(manual_tags) == 2
    assert all(tag.source == "manual" for tag in manual_tags)
