"""Regression tests for persistent AI training datasets."""

from unittest.mock import AsyncMock, patch

from sqlalchemy import select

from db.models import (
    Blob,
    Collection,
    CollectionGallery,
    Dataset,
    DatasetImage,
    Gallery,
    GalleryTag,
    Image,
    Tag,
    User,
)


async def _user(db, user_id: int, role: str = "member") -> User:
    user = User(
        id=user_id,
        username=f"dataset-user-{user_id}",
        password_hash="test",
        role=role,
    )
    db.add(user)
    await db.flush()
    return user


async def _gallery_with_images(
    db,
    *,
    owner_id: int,
    source_id: str,
    visibility: str = "private",
    active: int = 2,
    hidden: int = 0,
    tags: list[str] | None = None,
    dimensions: list[tuple[int | None, int | None]] | None = None,
    phashes: list[int | None] | None = None,
) -> tuple[Gallery, list[Image]]:
    gallery = Gallery(
        source="local",
        source_id=source_id,
        title=source_id,
        created_by_user_id=owner_id,
        visibility=visibility,
        tags_array=tags or [],
    )
    db.add(gallery)
    await db.flush()
    for value in tags or []:
        namespace, name = value.split(":", 1)
        tag = (await db.execute(select(Tag).where(Tag.namespace == namespace, Tag.name == name))).scalar_one_or_none()
        if tag is None:
            tag = Tag(namespace=namespace, name=name)
            db.add(tag)
            await db.flush()
        db.add(GalleryTag(gallery_id=gallery.id, tag_id=tag.id, source="metadata"))
    images = []
    for index in range(active + hidden):
        sha = f"dataset-{source_id}-{index}"
        width, height = dimensions[index] if dimensions is not None else (1024 + index, 1024)
        blob = Blob(
            sha256=sha,
            file_size=100,
            extension=".jpg",
            width=width,
            height=height,
            phash_int=phashes[index] if phashes is not None else None,
        )
        db.add(blob)
        await db.flush()
        image = Image(
            gallery_id=gallery.id,
            page_num=index + 1,
            filename=f"{index + 1}.jpg",
            blob_sha256=sha,
            visibility="active" if index < active else "hidden",
        )
        db.add(image)
        images.append(image)
    await db.commit()
    return gallery, images


async def test_dataset_endpoints_require_auth(unauthed_client):
    response = await unauthed_client.get("/api/datasets/")
    assert response.status_code == 401


async def test_dataset_endpoints_require_member_role(db_session, make_client):
    await _user(db_session, 1, role="viewer")
    await db_session.commit()

    async with make_client(user_id=1, role="viewer") as ac:
        response = await ac.get("/api/datasets/")

    assert response.status_code == 403


async def test_create_dataset_from_gallery_includes_only_active_images(db_session, make_client):
    await _user(db_session, 1)
    gallery, images = await _gallery_with_images(
        db_session,
        owner_id=1,
        source_id="gallery-selection",
        active=2,
        hidden=1,
    )

    with patch("routers.datasets.emit_safe", new_callable=AsyncMock) as emit:
        async with make_client(user_id=1) as ac:
            response = await ac.post(
                "/api/datasets/",
                json={"name": "Portrait LoRA", "gallery_ids": [gallery.id]},
            )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["member_count"] == 2
    assert body["gallery_count"] == 1
    assert body["excluded_count"] == 0
    assert body["selection_spec"] == {"gallery_ids": [gallery.id]}
    members = (
        (await db_session.execute(select(DatasetImage).where(DatasetImage.dataset_id == body["id"]))).scalars().all()
    )
    assert {member.image_id for member in members} == {images[0].id, images[1].id}
    assert {member.source for member in members} == {"gallery"}
    emit.assert_awaited_once()


async def test_create_dataset_reports_inaccessible_gallery_and_image(db_session, make_client):
    await _user(db_session, 1)
    await _user(db_session, 2)
    private_gallery, images = await _gallery_with_images(
        db_session,
        owner_id=2,
        source_id="other-users-private-gallery",
        visibility="private",
        active=1,
    )

    async with make_client(user_id=1) as ac:
        response = await ac.post(
            "/api/datasets/",
            json={
                "name": "No leaks",
                "gallery_ids": [private_gallery.id],
                "image_ids": [images[0].id],
            },
        )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["member_count"] == 0
    assert body["denied"] == {
        "gallery_ids": [private_gallery.id],
        "collection_ids": [],
        "image_ids": [images[0].id],
    }


async def test_create_dataset_from_collection_preserves_provenance(db_session, make_client):
    await _user(db_session, 1)
    gallery, images = await _gallery_with_images(
        db_session,
        owner_id=1,
        source_id="collection-gallery",
        active=1,
    )
    collection = Collection(user_id=1, name="Training candidates")
    db_session.add(collection)
    await db_session.flush()
    db_session.add(CollectionGallery(collection_id=collection.id, gallery_id=gallery.id))
    await db_session.commit()

    async with make_client(user_id=1) as ac:
        response = await ac.post(
            "/api/datasets/",
            json={"name": "From collection", "collection_ids": [collection.id]},
        )

    assert response.status_code == 201, response.text
    body = response.json()
    member = (
        await db_session.execute(
            select(DatasetImage).where(
                DatasetImage.dataset_id == body["id"],
                DatasetImage.image_id == images[0].id,
            )
        )
    ).scalar_one()
    assert member.source == "collection"


async def test_create_dataset_from_bounded_tag_query_respects_access(db_session, make_client):
    await _user(db_session, 1)
    await _user(db_session, 2)
    _, visible_images = await _gallery_with_images(
        db_session,
        owner_id=1,
        source_id="tag-query-visible",
        active=2,
        tags=["character:alice", "general:portrait"],
    )
    await _gallery_with_images(
        db_session,
        owner_id=1,
        source_id="tag-query-excluded",
        active=1,
        tags=["character:alice", "general:sketch"],
    )
    await _gallery_with_images(
        db_session,
        owner_id=2,
        source_id="tag-query-private",
        visibility="private",
        active=1,
        tags=["character:alice"],
    )

    async with make_client(user_id=1) as ac:
        response = await ac.post(
            "/api/datasets/",
            json={
                "name": "Tag query",
                "tag_query": "character:alice -general:sketch",
                "tag_query_limit": 1,
            },
        )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["member_count"] == 1
    assert body["tag_query_truncated"] is True
    assert body["selection_spec"] == {
        "tag_query": "character:alice -general:sketch",
        "tag_query_limit": 1,
    }
    member = (await db_session.execute(select(DatasetImage).where(DatasetImage.dataset_id == body["id"]))).scalar_one()
    assert member.image_id == visible_images[0].id
    assert member.source == "tag_query"


async def test_exclude_and_reinclude_dataset_image_is_durable(db_session, make_client):
    await _user(db_session, 1)
    _, images = await _gallery_with_images(
        db_session,
        owner_id=1,
        source_id="exclude-image",
        active=1,
    )

    async with make_client(user_id=1) as ac:
        created = await ac.post(
            "/api/datasets/",
            json={"name": "Reviewable", "image_ids": [images[0].id]},
        )
        dataset_id = created.json()["id"]
        excluded = await ac.delete(f"/api/datasets/{dataset_id}/images/{images[0].id}")
        excluded_view = await ac.get(f"/api/datasets/{dataset_id}?state=excluded")
        reincluded = await ac.post(
            f"/api/datasets/{dataset_id}/members",
            json={"image_ids": [images[0].id]},
        )
        included_view = await ac.get(f"/api/datasets/{dataset_id}")

    assert excluded.status_code == 200
    assert excluded_view.json()["excluded_count"] == 1
    assert excluded_view.json()["images"][0]["state"] == "excluded"
    assert excluded_view.json()["images"][0]["exclusion_reason"] == "manual"
    assert reincluded.json()["added"] == 1
    assert included_view.json()["member_count"] == 1
    assert included_view.json()["images"][0]["source"] == "manual"
    assert included_view.json()["images"][0]["thumb_url"].endswith(f"/{images[0].blob_sha256}/thumb_160.webp")


async def test_dataset_filters_preview_apply_and_relax_preserve_manual_exclusions(db_session, make_client):
    await _user(db_session, 1)
    _, images = await _gallery_with_images(
        db_session,
        owner_id=1,
        source_id="automatic-filters",
        active=4,
        dimensions=[(512, 512), (2048, 2048), (5000, 1200), (None, None)],
    )

    with patch("routers.datasets.emit_safe", new_callable=AsyncMock):
        async with make_client(user_id=1) as ac:
            created = await ac.post(
                "/api/datasets/",
                json={"name": "Filtered", "image_ids": [image.id for image in images]},
            )
            dataset_id = created.json()["id"]
            preview = await ac.post(
                f"/api/datasets/{dataset_id}/filters/preview",
                json={"min_width": 1024, "min_height": 1024, "max_aspect_ratio": 4},
            )
            before_apply = await ac.get(f"/api/datasets/{dataset_id}")
            applied = await ac.post(
                f"/api/datasets/{dataset_id}/filters/apply",
                json={"min_width": 1024, "min_height": 1024, "max_aspect_ratio": 4},
            )
            excluded = await ac.get(f"/api/datasets/{dataset_id}?state=excluded")
            await ac.delete(f"/api/datasets/{dataset_id}/images/{images[1].id}")
            relaxed = await ac.post(f"/api/datasets/{dataset_id}/filters/apply", json={})
            final_excluded = await ac.get(f"/api/datasets/{dataset_id}?state=excluded")
            final_included = await ac.get(f"/api/datasets/{dataset_id}")

    assert preview.status_code == 200, preview.text
    assert preview.json() == {
        "status": "ok",
        "filters": {
            "min_width": 1024,
            "min_height": 1024,
            "max_aspect_ratio": 4.0,
            "phash_distance": None,
        },
        "total": 4,
        "auto_excluded": 2,
        "newly_excluded": 2,
        "would_restore": 0,
        "manual_excluded": 0,
        "remaining": 2,
        "unknown_dimensions": 1,
        "unknown_phash": 0,
        "reasons": {"min_resolution": 1, "aspect_ratio": 1, "phash_duplicate": 0},
    }
    assert before_apply.json()["member_count"] == 4
    assert applied.json()["changed"] == 2
    assert {image["exclusion_reason"] for image in excluded.json()["images"]} == {
        "min_resolution",
        "aspect_ratio",
    }
    assert relaxed.json()["would_restore"] == 2
    assert relaxed.json()["manual_excluded"] == 1
    assert relaxed.json()["changed"] == 2
    assert final_excluded.json()["total"] == 1
    assert final_excluded.json()["images"][0]["id"] == images[1].id
    assert final_excluded.json()["images"][0]["exclusion_reason"] == "manual"
    assert final_included.json()["member_count"] == 3
    assert final_included.json()["selection_spec"]["filters"] == {
        "min_width": None,
        "min_height": None,
        "max_aspect_ratio": None,
        "phash_distance": None,
    }


async def test_dataset_phash_filter_keeps_first_and_restores_when_disabled(db_session, make_client):
    await _user(db_session, 1)
    _, images = await _gallery_with_images(
        db_session,
        owner_id=1,
        source_id="phash-filter",
        active=4,
        phashes=[0b0000, 0b0001, 0b1111, None],
    )

    with patch("routers.datasets.emit_safe", new_callable=AsyncMock):
        async with make_client(user_id=1) as ac:
            created = await ac.post(
                "/api/datasets/", json={"name": "pHash", "image_ids": [image.id for image in images]}
            )
            dataset_id = created.json()["id"]
            preview = await ac.post(
                f"/api/datasets/{dataset_id}/filters/preview", json={"phash_distance": 1}
            )
            applied = await ac.post(
                f"/api/datasets/{dataset_id}/filters/apply", json={"phash_distance": 1}
            )
            excluded = await ac.get(f"/api/datasets/{dataset_id}?state=excluded")
            relaxed = await ac.post(f"/api/datasets/{dataset_id}/filters/apply", json={})

    assert preview.status_code == 200, preview.text
    assert preview.json()["reasons"]["phash_duplicate"] == 1
    assert preview.json()["unknown_phash"] == 1
    assert applied.json()["changed"] == 1
    assert excluded.json()["images"][0]["id"] == images[1].id
    assert excluded.json()["images"][0]["exclusion_reason"] == "phash_duplicate"
    assert relaxed.json()["would_restore"] == 1


async def test_dataset_is_private_to_owner(db_session, make_client):
    await _user(db_session, 1)
    await _user(db_session, 2)
    dataset = Dataset(user_id=1, name="Owner only", selection_spec={})
    db_session.add(dataset)
    await db_session.commit()

    async with make_client(user_id=2) as ac:
        response = await ac.get(f"/api/datasets/{dataset.id}")

    assert response.status_code == 404


async def test_dataset_caption_review_and_batch_rewrite(db_session, make_client):
    await _user(db_session, 1)
    _, images = await _gallery_with_images(
        db_session,
        owner_id=1,
        source_id="caption-review",
        active=2,
    )

    async with make_client(user_id=1) as ac:
        with patch("routers.datasets.emit_safe", new_callable=AsyncMock):
            created = await ac.post(
                "/api/datasets/", json={"name": "Captions", "image_ids": [image.id for image in images]}
            )
            dataset_id = created.json()["id"]
            edited = await ac.patch(
                f"/api/datasets/{dataset_id}/images/{images[0].id}/caption",
                json={"caption": "a person in a forest"},
            )
            prepended = await ac.post(
                f"/api/datasets/{dataset_id}/captions/batch",
                json={"operation": "prepend_trigger", "trigger_word": "alice_token"},
            )
            replaced = await ac.post(
                f"/api/datasets/{dataset_id}/captions/batch",
                json={"operation": "search_replace", "search": "forest", "replacement": "garden"},
            )
            detail = await ac.get(f"/api/datasets/{dataset_id}")
    assert edited.json()["caption"] == "a person in a forest"
    assert prepended.json()["changed"] == 2
    assert replaced.json()["changed"] == 1
    assert detail.json()["images"][0]["caption"] == "alice_token, a person in a garden"


async def test_list_and_update_dataset_metadata(db_session, make_client):
    await _user(db_session, 1)

    async with make_client(user_id=1) as ac:
        invalid = await ac.post("/api/datasets/", json={"name": "   "})
        created = await ac.post(
            "/api/datasets/",
            json={"name": "Initial", "description": "first"},
        )
        dataset_id = created.json()["id"]
        updated = await ac.patch(
            f"/api/datasets/{dataset_id}",
            json={"name": "Renamed", "description": None},
        )
        listing = await ac.get("/api/datasets/")

    assert invalid.status_code == 422
    assert updated.status_code == 200
    assert listing.status_code == 200
    datasets = listing.json()["datasets"]
    assert len(datasets) == 1
    assert datasets[0]["id"] == dataset_id
    assert datasets[0]["name"] == "Renamed"
    assert datasets[0]["description"] is None
    assert datasets[0]["member_count"] == 0


async def test_delete_dataset_cascades_members(db_session, make_client):
    await _user(db_session, 1)
    _, images = await _gallery_with_images(
        db_session,
        owner_id=1,
        source_id="delete-dataset",
        active=1,
    )

    async with make_client(user_id=1) as ac:
        created = await ac.post(
            "/api/datasets/",
            json={"name": "Disposable", "image_ids": [images[0].id]},
        )
        dataset_id = created.json()["id"]
        deleted = await ac.delete(f"/api/datasets/{dataset_id}")

    assert deleted.status_code == 200
    assert await db_session.get(Dataset, dataset_id) is None
    members = (
        (await db_session.execute(select(DatasetImage).where(DatasetImage.dataset_id == dataset_id))).scalars().all()
    )
    assert members == []
