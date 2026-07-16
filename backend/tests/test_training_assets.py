"""Tests for LoRA library and ComfyUI PNG round-trip imports."""

import io
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

from PIL import Image as PILImage
from PIL.PngImagePlugin import PngInfo
from sqlalchemy import text

from db.models import Blob


async def _seed_user_dataset(db_session) -> None:
    await db_session.execute(
        text(
            "INSERT OR IGNORE INTO users (id, username, password_hash, role) "
            "VALUES (1, 'trainer', 'x', 'admin')"
        )
    )
    await db_session.execute(
        text("INSERT INTO datasets (id, user_id, name, selection_spec) VALUES (8001, 1, 'Training', '{}')")
    )
    await db_session.commit()


async def test_lora_upload_list_download_and_delete(client, db_session, tmp_path):
    await _seed_user_dataset(db_session)
    content = b"safe-tensors-placeholder"
    with patch("routers.training_assets.settings.data_training_path", str(tmp_path)):
        uploaded = await client.post(
            "/api/training/loras",
            data={
                "name": "Alice LoRA",
                "dataset_id": "8001",
                "trigger_words": "alice_token, alice_token, blue dress",
                "training_params": json.dumps({"steps": 1200, "network_dim": 32}),
            },
            files={"file": ("alice.safetensors", content, "application/octet-stream")},
        )
        model_id = uploaded.json()["id"]
        listed = await client.get("/api/training/loras")
        downloaded = await client.get(f"/api/training/loras/{model_id}/file")
        deleted = await client.delete(f"/api/training/loras/{model_id}")

    assert uploaded.status_code == 201, uploaded.text
    assert uploaded.json()["dataset_id"] == 8001
    assert uploaded.json()["trigger_words"] == ["alice_token", "blue dress"]
    assert listed.json()["loras"][0]["training_params"]["steps"] == 1200
    assert downloaded.content == content
    assert deleted.status_code == 200
    assert not list((tmp_path / "loras").rglob("*.safetensors"))


async def test_comfyui_png_import_preserves_workflow_metadata(
    client,
    db_session,
    tmp_path,
):
    await db_session.execute(
        text(
            "INSERT OR IGNORE INTO users (id, username, password_hash, role) "
            "VALUES (1, 'trainer', 'x', 'admin')"
        )
    )
    await db_session.commit()
    metadata = PngInfo()
    metadata.add_text("prompt", json.dumps({"1": {"inputs": {"text": "a forest"}}}))
    metadata.add_text("workflow", json.dumps({"nodes": [{"id": 1, "type": "CLIPTextEncode"}]}))
    payload = io.BytesIO()
    PILImage.new("RGB", (24, 32), "orange").save(payload, format="PNG", pnginfo=metadata)

    async def fake_store(path: Path, sha256: str, session):
        blob = Blob(
            sha256=sha256,
            file_size=path.stat().st_size,
            extension=".png",
            storage="external",
            external_path=str(path),
            ref_count=0,
        )
        session.add(blob)
        await session.flush()
        return blob

    with (
        patch("routers.training_assets.settings.data_training_path", str(tmp_path)),
        patch("routers.training_assets.store_blob", side_effect=fake_store),
        patch("routers.training_assets.create_library_symlink", new_callable=AsyncMock),
        patch("routers.training_assets.emit_safe", new_callable=AsyncMock),
    ):
        imported = await client.post(
            "/api/training/comfyui/import",
            data={"title": "Generated forest"},
            files={"file": ("comfy.png", payload.getvalue(), "image/png")},
        )
        result = imported.json()
        saved = await client.get(f"/api/training/comfyui/images/{result['image_id']}/metadata")

    assert imported.status_code == 201, imported.text
    assert result["has_prompt"] is True
    assert result["has_workflow"] is True
    assert saved.status_code == 200
    assert saved.json()["prompt"]["1"]["inputs"]["text"] == "a forest"
    assert saved.json()["workflow"]["nodes"][0]["type"] == "CLIPTextEncode"


async def test_training_assets_require_auth(unauthed_client):
    assert (await unauthed_client.get("/api/training/loras")).status_code == 401
