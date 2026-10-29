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
        text("INSERT INTO users (id, username, password_hash, role) VALUES (1, 'admin', 'unused', 'admin')")
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
    await db_session.execute(text("INSERT INTO collections (id, user_id, name) VALUES (401, 1, 'Merged collection')"))
    await db_session.execute(
        text("INSERT INTO collection_galleries (collection_id, gallery_id, position) VALUES (401, 102, 0)")
    )
    await db_session.execute(text("INSERT INTO user_favorites (user_id, gallery_id) VALUES (1, 102)"))
    await db_session.execute(text("INSERT INTO user_ratings (user_id, gallery_id, rating) VALUES (1, 102, 8)"))
    await db_session.execute(
        text("INSERT INTO read_progress (user_id, gallery_id, last_page, last_image_id) VALUES (1, 102, 2, 203)")
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
        (await db_session.execute(select(UserFavorite).where(UserFavorite.gallery_id.in_([101, 102])))).scalars().all()
    )
    memberships = (
        (await db_session.execute(select(CollectionGallery).where(CollectionGallery.collection_id == 901)))
        .scalars()
        .all()
    )
    manual_tags = (
        (await db_session.execute(select(GalleryTag).where(GalleryTag.gallery_id.in_([101, 102])))).scalars().all()
    )
    assert len(favorites) == 2
    assert len(memberships) == 2
    assert len(manual_tags) == 2
    assert all(tag.source == "manual" for tag in manual_tags)


async def test_merge_with_pending_pages_is_rejected_with_409(client, db_session):
    """Both the preview and the merge refuse a selection holding a page that
    has no blob yet (a link page still waiting for its hash)."""
    await _seed_user_and_galleries(db_session)
    await db_session.execute(
        text("INSERT INTO blobs (sha256, file_size, extension, ref_count) VALUES ('sha-a', 100, 'jpg', 1)")
    )
    await db_session.execute(
        text(
            "INSERT INTO images (id, gallery_id, page_num, filename, blob_sha256, external_path) VALUES "
            "(201, 101, 1, 'target.jpg', 'sha-a', NULL), "
            "(202, 102, 1, 'pending.jpg', NULL, '/mnt/lib/two/pending.jpg')"
        )
    )
    await db_session.commit()
    body = {"gallery_ids": [101, 102], "target_id": 101}

    preview = await client.post("/api/explorer/merge/preview", json=body)
    with patch("core.audit.log_audit", new_callable=AsyncMock):
        merged = await client.post("/api/explorer/merge", json=body)

    for response in (preview, merged):
        assert response.status_code == 409, response.text
        assert response.json()["detail"] == "Wait for pages to finish processing before merging galleries"
    assert (await db_session.get(Gallery, 102)).deleted_at is None


# ---------------------------------------------------------------------------
# Gallery image listing, size sort, hidden-images smart view
# ---------------------------------------------------------------------------

_SHA = {name: name[0] * 64 for name in ("a1", "b2", "c3", "d4", "e5", "f6")}


async def _seed_listing(db_session) -> None:
    """Gallery 101: 3 active (image 300B, video 100B, gif 200B) + hidden 50B + hidden pending."""
    await _seed_user_and_galleries(db_session)
    await db_session.execute(
        text(
            "INSERT INTO blobs (sha256, file_size, media_type, extension, storage, ref_count) VALUES "
            f"('{_SHA['a1']}', 300, 'image', '.jpg', 'cas', 2), "
            f"('{_SHA['b2']}', 100, 'video', '.mp4', 'cas', 1), "
            f"('{_SHA['c3']}', 200, 'gif', '.gif', 'cas', 1), "
            f"('{_SHA['d4']}', 50, 'image', '.png', 'cas', 1)"
        )
    )
    await db_session.execute(
        text(
            "INSERT INTO images (id, gallery_id, page_num, filename, blob_sha256, external_path, visibility, "
            "hidden_at, source_position) VALUES "
            f"(1, 101, 1, 'p1.jpg', '{_SHA['a1']}', NULL, 'active', NULL, 1), "
            f"(2, 101, 2, 'p2.mp4', '{_SHA['b2']}', NULL, 'active', NULL, 2), "
            f"(3, 101, 3, 'p3.gif', '{_SHA['c3']}', NULL, 'active', NULL, 3), "
            f"(4, 101, -4, 'h4.png', '{_SHA['d4']}', NULL, 'user_hidden', '2026-01-01 00:00:00', 4), "
            "(5, 101, -5, 'h5.jpg', NULL, '/mnt/lib/h5.jpg', 'user_hidden', '2026-01-01 00:00:00', 5), "
            f"(6, 102, 1, 'other.jpg', '{_SHA['a1']}', NULL, 'active', NULL, 1)"
        )
    )
    await db_session.commit()


def _ids(response) -> list[int]:
    return [item["image_id"] for item in response.json()["items"]]


async def test_gallery_images_default_lists_only_active_pages_in_page_order(client, db_session):
    await _seed_listing(db_session)

    response = await client.get("/api/explorer/galleries/101/images")

    assert response.status_code == 200, response.text
    assert _ids(response) == [1, 2, 3]
    assert response.json()["total"] == 3
    assert [item["page_num"] for item in response.json()["items"]] == [1, 2, 3]
    assert {item["visibility"] for item in response.json()["items"]} == {"active"}


async def test_gallery_images_hidden_visibility_lists_hidden_rows_with_null_page_num(client, db_session):
    await _seed_listing(db_session)

    response = await client.get("/api/explorer/galleries/101/images", params={"visibility": "hidden"})

    assert response.status_code == 200, response.text
    assert _ids(response) == [4, 5]
    items = response.json()["items"]
    assert [item["page_num"] for item in items] == [None, None]
    assert [item["visibility"] for item in items] == ["hidden", "hidden"]
    assert items[0]["hidden_at"] is not None
    assert items[1]["storage"] == "pending" and items[1]["file_size"] is None


async def test_gallery_images_all_visibility_lists_active_pages_before_hidden_rows(client, db_session):
    await _seed_listing(db_session)

    response = await client.get("/api/explorer/galleries/101/images", params={"visibility": "all"})

    assert _ids(response) == [1, 2, 3, 4, 5]
    assert response.json()["total"] == 5
    desc = await client.get("/api/explorer/galleries/101/images", params={"visibility": "all", "direction": "desc"})
    assert _ids(desc) == [5, 4, 3, 2, 1]


async def test_gallery_images_media_filter_returns_only_matching_blob_media_type(client, db_session):
    await _seed_listing(db_session)

    video = await client.get("/api/explorer/galleries/101/images", params={"media": "video"})
    gif = await client.get("/api/explorer/galleries/101/images", params={"media": "gif"})
    image_all = await client.get("/api/explorer/galleries/101/images", params={"media": "image", "visibility": "all"})

    assert _ids(video) == [2] and video.json()["total"] == 1
    assert _ids(gif) == [3]
    # Pending (blob-less) rows only appear under media=all.
    assert _ids(image_all) == [1, 4]


async def test_gallery_images_sort_size_orders_by_blob_bytes_with_pending_last(client, db_session):
    await _seed_listing(db_session)
    params = {"visibility": "all", "sort": "size"}

    desc = await client.get("/api/explorer/galleries/101/images", params={**params, "direction": "desc"})
    asc = await client.get("/api/explorer/galleries/101/images", params={**params, "direction": "asc"})

    assert _ids(asc) == [4, 2, 3, 1, 5]
    assert [item["file_size"] for item in desc.json()["items"]][:4] == [300, 200, 100, 50]
    assert _ids(desc)[:4] == [1, 3, 2, 4]
    assert _ids(desc)[-1] == 5 and _ids(asc)[-1] == 5


async def test_gallery_images_pagination_reports_total_and_offset(client, db_session):
    await _seed_listing(db_session)

    response = await client.get("/api/explorer/galleries/101/images", params={"limit": 2, "offset": 1})

    body = response.json()
    assert (body["total"], body["offset"], body["limit"]) == (3, 1, 2)
    assert _ids(response) == [2, 3]
    tail = await client.get("/api/explorer/galleries/101/images", params={"limit": 2, "offset": 2})
    assert _ids(tail) == [3]


async def test_gallery_images_shared_flag_true_only_for_blob_used_by_another_gallery(client, db_session):
    await _seed_listing(db_session)

    response = await client.get("/api/explorer/galleries/101/images", params={"visibility": "all"})

    shared = {item["image_id"]: item["shared"] for item in response.json()["items"]}
    assert shared == {1: True, 2: False, 3: False, 4: False, 5: False}


async def test_gallery_images_summary_counts_and_reclaimable_bytes(client, db_session):
    await _seed_listing(db_session)

    summary = (await client.get("/api/explorer/galleries/101/images")).json()["summary"]

    assert summary == {
        "active_count": 3,
        "hidden_count": 2,
        "active_bytes": 600,
        "hidden_bytes": 50,
        "hidden_reclaimable_bytes": 50,
    }
    assert (await client.get("/api/explorer/galleries/101/images")).json()["can_edit"] is True


async def test_gallery_images_summary_hidden_blob_shared_elsewhere_is_not_reclaimable(client, db_session):
    await _seed_listing(db_session)
    await db_session.execute(
        text(
            "INSERT INTO images (id, gallery_id, page_num, filename, blob_sha256, visibility) "
            f"VALUES (7, 102, 2, 'twin.png', '{_SHA['d4']}', 'active')"
        )
    )
    await db_session.commit()

    summary = (await client.get("/api/explorer/galleries/101/images")).json()["summary"]

    assert summary["hidden_bytes"] == 50
    assert summary["hidden_reclaimable_bytes"] == 0


async def test_gallery_images_excluded_blob_hides_active_page_but_not_hidden_row(client, db_session):
    await _seed_listing(db_session)
    await db_session.execute(
        text(
            f"INSERT INTO excluded_blobs (gallery_id, blob_sha256) VALUES (101, '{_SHA['c3']}'), (101, '{_SHA['d4']}')"
        )
    )
    await db_session.commit()

    response = await client.get("/api/explorer/galleries/101/images", params={"visibility": "all"})

    # p3 (active, excluded) is gone; the hidden row stays so it can be restored/purged.
    assert _ids(response) == [1, 2, 4, 5]


async def test_gallery_images_other_users_private_gallery_returns_404(make_client, db_session):
    await _seed_listing(db_session)
    await db_session.execute(text("UPDATE galleries SET visibility='private' WHERE id=101"))
    await db_session.execute(
        text("INSERT INTO users (id, username, password_hash, role) VALUES (2, 'u2', 'x', 'member')")
    )
    await db_session.commit()

    async with make_client(user_id=2, role="member") as ac:
        hidden = await ac.get("/api/explorer/galleries/101/images")
        public = await ac.get("/api/explorer/galleries/102/images")

    assert hidden.status_code == 404
    assert public.status_code == 200


async def test_gallery_images_trashed_gallery_returns_404(client, db_session):
    await _seed_listing(db_session)
    await db_session.execute(text("UPDATE galleries SET deleted_at='2026-01-01 00:00:00' WHERE id=101"))
    await db_session.commit()

    assert (await client.get("/api/explorer/galleries/101/images")).status_code == 404


async def test_gallery_images_requires_auth(unauthed_client):
    assert (await unauthed_client.get("/api/explorer/galleries/101/images")).status_code == 401


async def _seed_size_galleries(db_session) -> None:
    await _seed_listing(db_session)
    # 101 has 600 active bytes + 50 hidden; 102 has 300; 103 has 900 active + a huge hidden blob; 104 is empty.
    await db_session.execute(
        text(
            "INSERT INTO galleries (id, source, source_id, title, visibility, created_by_user_id) VALUES "
            "(103, 'local', 'three', 'Three', 'public', 1), (104, 'local', 'four', 'Four', 'public', 1)"
        )
    )
    await db_session.execute(
        text(
            "INSERT INTO blobs (sha256, file_size, media_type, extension, storage, ref_count) VALUES "
            f"('{_SHA['e5']}', 900, 'image', '.jpg', 'cas', 1), ('{_SHA['f6']}', 99999, 'image', '.jpg', 'cas', 1)"
        )
    )
    await db_session.execute(
        text(
            "INSERT INTO images (id, gallery_id, page_num, filename, blob_sha256, visibility, hidden_at) VALUES "
            f"(31, 103, 1, 'big.jpg', '{_SHA['e5']}', 'active', NULL), "
            f"(32, 103, -2, 'huge_hidden.jpg', '{_SHA['f6']}', 'user_hidden', '2026-01-01 00:00:00')"
        )
    )
    await db_session.commit()


async def test_query_sort_size_orders_galleries_by_active_image_bytes_ignoring_hidden(client, db_session):
    await _seed_size_galleries(db_session)
    body = {"node_kind": "source", "node_id": "local", "sort": "size"}

    desc = await client.post("/api/explorer/query", json={**body, "direction": "desc"})
    asc = await client.post("/api/explorer/query", json={**body, "direction": "asc"})

    assert desc.status_code == 200, desc.text
    # Active bytes: 103=900, 101=600, 102=300, 104=0 (103's 99,999-byte hidden blob is not counted).
    assert [item["id"] for item in desc.json()["items"]] == [103, 101, 102, 104]
    assert [item["id"] for item in asc.json()["items"]] == [104, 102, 101, 103]


async def test_query_sort_size_hidden_bytes_do_not_change_rank(client, db_session):
    await _seed_size_galleries(db_session)
    # 102: 300 active bytes; give it a giant hidden image. Rank must stay below 101 (600 active).
    await db_session.execute(
        text(
            "INSERT INTO images (id, gallery_id, page_num, filename, blob_sha256, visibility, hidden_at) VALUES "
            f"(33, 102, -2, 'giant_hidden.jpg', '{_SHA['f6']}', 'user_hidden', '2026-01-01 00:00:00')"
        )
    )
    await db_session.commit()

    response = await client.post(
        "/api/explorer/query",
        json={"node_kind": "source", "node_id": "local", "sort": "size", "direction": "desc"},
    )

    assert [item["id"] for item in response.json()["items"]] == [103, 101, 102, 104]


async def test_query_smart_hidden_images_lists_only_galleries_with_hidden_images(client, db_session):
    await _seed_size_galleries(db_session)

    response = await client.post(
        "/api/explorer/query",
        json={"node_kind": "smart", "node_id": "hidden_images", "sort": "title", "direction": "asc"},
    )

    assert response.status_code == 200, response.text
    assert sorted(item["id"] for item in response.json()["items"]) == [101, 103]
    assert response.json()["total"] == 2


async def test_roots_smart_views_report_hidden_images_galleries_and_bytes(client, db_session):
    await _seed_size_galleries(db_session)

    response = await client.get("/api/explorer/roots")

    assert response.status_code == 200, response.text
    smart = response.json()["virtual"]["smart_views"]
    assert smart["hidden_images"] == 2
    assert smart["hidden_bytes"] == 50 + 99999


# ── Category registry: bulk metadata validation, category node, /roots ───────


async def _seed_registry(db_session) -> None:
    await db_session.execute(
        text(
            "INSERT INTO gallery_categories (name, color, sort_order, is_builtin) VALUES "
            "('Manga', 'orange', 2, 1), ('Doujinshi', 'pink', 1, 1), ('Cosplay', 'red', 3, 1)"
        )
    )
    await db_session.commit()


async def _categories(db_session, ids) -> dict[int, str | None]:
    db_session.expire_all()
    rows = (await db_session.execute(select(Gallery.id, Gallery.category).where(Gallery.id.in_(ids)))).all()
    return {row.id: row.category for row in rows}


async def test_bulk_metadata_unknown_category_returns_400_and_keeps_existing_values(client, db_session):
    await _seed_user_and_galleries(db_session)
    await _seed_registry(db_session)
    await db_session.execute(text("UPDATE galleries SET category='Doujinshi' WHERE id=102"))
    await db_session.commit()

    response = await client.post(
        "/api/explorer/operations/metadata",
        json={
            "gallery_ids": [101, 102],
            "fields": {
                "title": {"mode": "set", "value": "Should not be written"},
                "category": {"mode": "set", "value": "Mnaga"},
            },
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Unknown category: Mnaga"
    assert await _categories(db_session, [101, 102]) == {101: "Manga", 102: "Doujinshi"}
    titles = (await db_session.execute(select(Gallery.title).where(Gallery.id.in_([101, 102])))).scalars().all()
    assert sorted(titles) == ["Old one", "Old two"]
    assert (await db_session.execute(select(GalleryMetadataChange))).scalars().all() == []
    assert (await db_session.execute(select(GalleryMetadataFieldState))).scalars().all() == []


async def test_bulk_metadata_category_value_matches_registry_case_insensitively_and_stores_canonical_name(
    client, db_session
):
    await _seed_user_and_galleries(db_session)
    await _seed_registry(db_session)

    response = await client.post(
        "/api/explorer/operations/metadata",
        json={"gallery_ids": [101, 102], "fields": {"category": {"mode": "set", "value": "  cOsPlAy "}}},
    )

    assert response.status_code == 200, response.text
    assert await _categories(db_session, [101, 102]) == {101: "Cosplay", 102: "Cosplay"}


async def test_bulk_metadata_blank_category_value_with_set_mode_clears_category(client, db_session):
    await _seed_user_and_galleries(db_session)
    await _seed_registry(db_session)

    response = await client.post(
        "/api/explorer/operations/metadata",
        json={"gallery_ids": [101, 102], "fields": {"category": {"mode": "set", "value": "   "}}},
    )

    assert response.status_code == 200, response.text
    assert await _categories(db_session, [101, 102]) == {101: None, 102: None}

    empty = await client.post(
        "/api/explorer/operations/metadata",
        json={"gallery_ids": [101], "fields": {"category": {"mode": "set", "value": ""}}},
    )
    assert empty.status_code == 200, empty.text


async def test_gallery_patch_unknown_category_returns_400_and_keeps_existing_category(client, db_session):
    await _seed_user_and_galleries(db_session)
    await _seed_registry(db_session)

    response = await client.patch(
        "/api/library/galleries/local/one",
        json={"title": "Renamed", "category": "Not A Category"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Unknown category: Not A Category"
    assert await _categories(db_session, [101]) == {101: "Manga"}
    db_session.expire_all()
    assert (await db_session.get(Gallery, 101)).title == "Old one"


async def _seed_category_galleries(db_session) -> None:
    await _seed_user_and_galleries(db_session)
    await _seed_registry(db_session)
    await db_session.execute(
        text(
            "INSERT INTO galleries "
            "(id, source, source_id, title, category, visibility, created_by_user_id) VALUES "
            "(103, 'local', 'three', 'Three', NULL, 'public', 1), "
            "(104, 'local', 'four', 'Four', '', 'public', 1), "
            "(105, 'local', 'five', 'Five', 'Legacy', 'public', 1), "
            "(106, 'local', 'six', 'Six', 'Doujinshi', 'public', 1)"
        )
    )
    await db_session.commit()


async def test_query_category_node_filters_by_exact_category_name(client, db_session):
    await _seed_category_galleries(db_session)

    response = await client.post("/api/explorer/query", json={"node_kind": "category", "node_id": "Manga"})

    assert response.status_code == 200, response.text
    assert sorted(item["id"] for item in response.json()["items"]) == [101, 102]
    assert response.json()["total"] == 2


async def test_query_category_node_uncategorized_sentinel_matches_null_and_empty_category(client, db_session):
    await _seed_category_galleries(db_session)

    response = await client.post("/api/explorer/query", json={"node_kind": "category", "node_id": "__uncategorized__"})

    assert response.status_code == 200, response.text
    assert sorted(item["id"] for item in response.json()["items"]) == [103, 104]


async def test_roots_categories_report_counts_zero_count_registry_entry_and_unregistered_legacy_value(
    client, db_session
):
    await _seed_category_galleries(db_session)
    await db_session.execute(text("UPDATE galleries SET deleted_at='2026-01-01 00:00:00' WHERE id=102"))
    await db_session.commit()

    response = await client.get("/api/explorer/roots")

    assert response.status_code == 200, response.text
    assert response.json()["virtual"]["categories"] == {
        "uncategorized": 2,
        "items": [
            {"id": "Doujinshi", "label": "Doujinshi", "gallery_count": 1, "registered": True},
            {"id": "Manga", "label": "Manga", "gallery_count": 1, "registered": True},
            {"id": "Cosplay", "label": "Cosplay", "gallery_count": 0, "registered": True},
            {"id": "Legacy", "label": "Legacy", "gallery_count": 1, "registered": False},
        ],
    }


async def test_roots_categories_exclude_other_users_private_galleries(make_client, db_session):
    await _seed_category_galleries(db_session)
    await db_session.execute(text("UPDATE galleries SET visibility='private' WHERE id IN (101, 103, 105)"))
    await db_session.execute(
        text("INSERT INTO users (id, username, password_hash, role) VALUES (2, 'u2', 'x', 'member')")
    )
    await db_session.commit()

    # Members also get the physical roots, which touches Redis; there are no
    # enabled library paths here so a bare mock is enough.
    with patch("routers.explorer.get_redis", return_value=AsyncMock()):
        async with make_client(user_id=2, role="member") as ac:
            response = await ac.get("/api/explorer/roots")

    assert response.status_code == 200, response.text
    categories = response.json()["virtual"]["categories"]
    assert categories["uncategorized"] == 1  # only 104; private 103 is hidden
    counts = {item["id"]: item["gallery_count"] for item in categories["items"]}
    assert counts == {"Doujinshi": 1, "Manga": 1, "Cosplay": 0}  # private 101 and legacy 105 not counted


# ── Category filter + facet counts inside a gallery-list node ────────────────


async def _seed_category_filter_galleries(db_session) -> None:
    """Local: 101/102 Manga, 103 NULL, 104 '', 105 Legacy, 106 Doujinshi.

    Plus an ehentai set (201 Manga 'alpha', 202 NULL 'beta', 203 Cosplay, 204
    Manga trashed) so source scoping is observable.
    """
    await _seed_category_galleries(db_session)
    await db_session.execute(
        text("INSERT INTO users (id, username, password_hash, role) VALUES (2, 'u2', 'x', 'member')")
    )
    await db_session.execute(
        text(
            "INSERT INTO galleries "
            "(id, source, source_id, title, category, visibility, created_by_user_id, deleted_at) VALUES "
            "(201, 'ehentai', 'e1', 'alpha one', 'Manga', 'public', 1, NULL), "
            "(202, 'ehentai', 'e2', 'beta two', NULL, 'public', 1, NULL), "
            "(203, 'ehentai', 'e3', 'alpha three', 'Cosplay', 'public', 1, NULL), "
            "(204, 'ehentai', 'e4', 'alpha four', 'Manga', 'public', 1, '2026-01-01 00:00:00'), "
            "(205, 'ehentai', 'e5', 'private five', NULL, 'private', 2, NULL)"
        )
    )
    await db_session.commit()


async def _query_ids(client, **body) -> list[int]:
    response = await client.post("/api/explorer/query", json=body)
    assert response.status_code == 200, response.text
    return sorted(item["id"] for item in response.json()["items"])


async def test_query_source_node_with_uncategorized_category_filter_returns_only_uncategorized_in_that_source(
    client, db_session
):
    await _seed_category_filter_galleries(db_session)

    assert await _query_ids(client, node_kind="source", node_id="local", category="__uncategorized__") == [103, 104]
    assert await _query_ids(client, node_kind="source", node_id="ehentai", category="__uncategorized__") == [
        202,
        205,  # admin also sees the other user's private gallery
    ]


async def test_query_source_node_with_named_category_filter_returns_exact_matches_in_that_source(client, db_session):
    await _seed_category_filter_galleries(db_session)

    assert await _query_ids(client, node_kind="source", node_id="local", category="Manga") == [101, 102]
    assert await _query_ids(client, node_kind="source", node_id="ehentai", category="Manga") == [201]
    assert await _query_ids(client, node_kind="source", node_id="local", category="manga") == []


async def test_query_without_category_filter_is_unchanged_by_category_support(client, db_session):
    await _seed_category_filter_galleries(db_session)

    assert await _query_ids(client, node_kind="source", node_id="ehentai") == [201, 202, 203, 205]


async def test_query_category_filter_combines_with_search_token(client, db_session):
    await _seed_category_filter_galleries(db_session)

    ids = await _query_ids(client, node_kind="source", node_id="ehentai", query="alpha", category="Manga")
    assert ids == [201]
    assert await _query_ids(client, node_kind="all", query="alpha", category="Cosplay") == [203]


async def test_query_saved_search_node_keeps_category_filter_after_expansion(client, db_session):
    await _seed_category_filter_galleries(db_session)
    await db_session.execute(
        text("INSERT INTO saved_searches (id, user_id, name, query, params) VALUES (7, 1, 'alphas', 'alpha', '{}')")
    )
    await db_session.commit()

    assert await _query_ids(client, node_kind="saved_search", node_id="7") == [201, 203]
    assert await _query_ids(client, node_kind="saved_search", node_id="7", category="Cosplay") == [203]
    assert await _query_ids(client, node_kind="saved_search", node_id="7", category="__uncategorized__") == []


async def test_query_trash_node_with_category_filter_returns_only_matching_trashed_galleries(client, db_session):
    await _seed_category_filter_galleries(db_session)

    assert await _query_ids(client, node_kind="trash", category="Manga") == [204]
    assert await _query_ids(client, node_kind="trash", category="Cosplay") == []


async def test_query_category_filter_composes_with_category_node(client, db_session):
    await _seed_category_filter_galleries(db_session)

    assert await _query_ids(client, node_kind="category", node_id="Manga", category="Manga") == [101, 102, 201]
    assert await _query_ids(client, node_kind="category", node_id="Manga", category="Cosplay") == []


async def test_selection_with_category_filter_materializes_only_matching_ids(client, db_session, mock_redis):
    await _seed_category_filter_galleries(db_session)
    saved: dict[str, str] = {}

    async def remember_setex(key, _ttl, value):
        saved[key] = value
        return True

    mock_redis.setex.side_effect = remember_setex

    response = await client.post(
        "/api/explorer/selections",
        json={"query": {"node_kind": "source", "node_id": "local", "category": "Manga"}},
    )

    assert response.status_code == 201, response.text
    assert response.json()["count"] == 2
    import json

    payload = json.loads(next(iter(saved.values())))
    assert sorted(payload["gallery_ids"]) == [101, 102]
    assert payload["created_from"]["category"] == "Manga"


async def test_selection_saved_search_node_with_category_filter_materializes_only_matching_ids(
    client, db_session, mock_redis
):
    await _seed_category_filter_galleries(db_session)
    await db_session.execute(
        text("INSERT INTO saved_searches (id, user_id, name, query, params) VALUES (7, 1, 'alphas', 'alpha', '{}')")
    )
    await db_session.commit()

    response = await client.post(
        "/api/explorer/selections",
        json={"query": {"node_kind": "saved_search", "node_id": "7", "category": "Cosplay"}},
    )

    assert response.status_code == 201, response.text
    assert response.json()["count"] == 1


async def test_query_facets_counts_ignore_active_category_filter_and_scope_to_node(client, db_session):
    await _seed_category_filter_galleries(db_session)

    response = await client.post(
        "/api/explorer/query",
        json={"node_kind": "source", "node_id": "local", "category": "Manga", "facets": True},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert sorted(item["id"] for item in body["items"]) == [101, 102]
    assert body["total"] == 2
    assert body["category_counts"] == {"Manga": 2, "__uncategorized__": 2, "Legacy": 1, "Doujinshi": 1}


async def test_query_facets_counts_respect_search_token_and_exclude_trashed(client, db_session):
    await _seed_category_filter_galleries(db_session)

    response = await client.post(
        "/api/explorer/query",
        json={"node_kind": "source", "node_id": "ehentai", "query": "alpha", "facets": True},
    )

    assert response.status_code == 200, response.text
    # 204 is a trashed Manga; 202/205 do not match "alpha".
    assert response.json()["category_counts"] == {"Manga": 1, "Cosplay": 1}


async def test_query_facets_counts_respect_access_filter(make_client, db_session):
    await _seed_category_filter_galleries(db_session)

    async with make_client(user_id=2, role="viewer") as ac:
        response = await ac.post(
            "/api/explorer/query",
            json={"node_kind": "source", "node_id": "ehentai", "facets": True},
        )

    assert response.status_code == 200, response.text
    # user 2 sees public 201-203 plus own private 205 (uncategorized).
    assert response.json()["category_counts"] == {"Manga": 1, "Cosplay": 1, "__uncategorized__": 2}


async def test_query_facets_on_trash_node_counts_trashed_galleries_only(client, db_session):
    await _seed_category_filter_galleries(db_session)

    response = await client.post("/api/explorer/query", json={"node_kind": "trash", "facets": True})

    assert response.status_code == 200, response.text
    assert response.json()["category_counts"] == {"Manga": 1}


async def test_query_without_facets_flag_omits_category_counts(client, db_session):
    await _seed_category_filter_galleries(db_session)

    response = await client.post("/api/explorer/query", json={"node_kind": "all"})

    assert response.status_code == 200, response.text
    assert "category_counts" not in response.json()
