"""Regression tests for trainer-ready dataset exports."""

import io
import json
import zipfile
from pathlib import Path
from unittest.mock import patch

from PIL import Image as PILImage
from sqlalchemy import text


async def _seed_dataset(db_session, image_path: Path) -> int:
    await db_session.execute(
        text(
            "INSERT OR IGNORE INTO users (id, username, password_hash, role) "
            "VALUES (1, 'exporter', 'x', 'admin')"
        )
    )
    await db_session.execute(
        text(
            "INSERT INTO galleries "
            "(id, source, source_id, title, pages, visibility, created_by_user_id, source_url, tags_array) "
            "VALUES (7100, 'local', 'trainer', 'Trainer', 1, 'private', 1, "
            "'https://example.test/gallery', '[\"character:alice\", \"style:anime\"]')"
        )
    )
    await db_session.execute(
        text(
            "INSERT INTO blobs "
            "(sha256, file_size, extension, storage, external_path, ref_count, width, height) "
            "VALUES ('dataset-export-sha', :size, '.png', 'external', :path, 1, 32, 48)"
        ),
        {"size": image_path.stat().st_size, "path": str(image_path)},
    )
    await db_session.execute(
        text(
            "INSERT INTO images "
            "(id, gallery_id, page_num, filename, blob_sha256, visibility, source_item_url, tags_array, caption) "
            "VALUES (7100, 7100, 1, '../unsafe.png', 'dataset-export-sha', 'active', "
            "'https://example.test/image', '[\"quality:high\"]', 'A person beneath flowering trees.')"
        )
    )
    await db_session.execute(
        text("INSERT INTO datasets (id, user_id, name, selection_spec) VALUES (7100, 1, 'Alice Set', '{}')")
    )
    await db_session.execute(
        text(
            "INSERT INTO dataset_images (dataset_id, image_id, state, source) "
            "VALUES (7100, 7100, 'included', 'manual')"
        )
    )
    await db_session.commit()
    return 7100


async def test_kohya_dataset_export_contains_config_split_captions_and_metadata(
    client, db_session, db_session_factory, tmp_path
):
    image_path = tmp_path / "source.png"
    PILImage.new("RGB", (32, 48), "purple").save(image_path)
    dataset_id = await _seed_dataset(db_session, image_path)

    with patch("routers.export.async_session", db_session_factory):
        response = await client.get(
            f"/api/export/dataset/{dataset_id}",
            params={
                "preset": "kohya",
                "trigger_word": "alice_token",
                "repeats": 3,
                "resolution": 512,
                "precompute_buckets": "true",
            },
        )

    assert response.status_code == 200, response.text
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = archive.namelist()
        image_name = next(name for name in names if name.endswith(".png"))
        caption_name = str(Path(image_name).with_suffix(".txt"))
        metadata_name = next(name for name in names if name.startswith("metadata/"))
        manifest = json.loads(archive.read("manifest.json"))

        assert image_name.startswith("train/3_alice_token/buckets/64x64/")
        assert "../" not in image_name
        assert archive.read(caption_name).decode() == "alice_token, A person beneath flowering trees."
        assert 'image_dir = "train/3_alice_token"' in archive.read("dataset.toml").decode()
        assert json.loads(archive.read(metadata_name))["source_url"] == "https://example.test/image"
        assert manifest["images"][0]["original_tags"] == [
            "character:alice",
            "quality:high",
            "style:anime",
        ]


async def test_ai_toolkit_dataset_export_contains_yaml(client, db_session, db_session_factory, tmp_path):
    image_path = tmp_path / "source.png"
    PILImage.new("RGB", (32, 48), "green").save(image_path)
    dataset_id = await _seed_dataset(db_session, image_path)

    with patch("routers.export.async_session", db_session_factory):
        response = await client.get(
            f"/api/export/dataset/{dataset_id}", params={"preset": "ai_toolkit", "repeats": 4}
        )

    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert "config.yaml" in archive.namelist()
        assert any(name.startswith("images/train/") and name.endswith(".png") for name in archive.namelist())
        config = archive.read("config.yaml").decode()
        assert "folder_path: images/train" in config
        assert "num_repeats: 4" in config


async def test_dataset_export_requires_auth(unauthed_client):
    response = await unauthed_client.get("/api/export/dataset/7100")
    assert response.status_code == 401
