"""Regression tests for Processable plugins and reversible image processing."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

from PIL import Image as PILImage
from sqlalchemy import select, text

from db.models import Blob, Image
from plugins.base import Processable
from plugins.builtin.swarmui.plugin import SwarmUiPlugin
from plugins.registry import PluginRegistry
from worker.process import _replace_processed_image


def test_swarmui_is_discovered_as_processable():
    plugin = SwarmUiPlugin()
    registry = PluginRegistry()

    registry.register(plugin)

    assert isinstance(plugin, Processable)
    assert registry.get_processor("swarmui") is plugin
    assert [meta.source_id for meta in registry.list_plugins()] == ["swarmui"]


async def test_swarmui_health_reports_disabled_without_network():
    plugin = SwarmUiPlugin()
    with patch("plugins.builtin.swarmui.plugin.get_toggle", new=AsyncMock(return_value=False)):
        health = await plugin.health()

    assert health.online is False
    assert health.error == "SwarmUI is disabled"


async def test_process_job_preserves_original_as_replacement_history(
    db_session,
    db_session_factory,
    tmp_path,
):
    input_path = tmp_path / "original.png"
    output_path = tmp_path / "upscaled.png"
    PILImage.new("RGB", (4, 5), "red").save(input_path)
    PILImage.new("RGB", (8, 10), "blue").save(output_path)

    await db_session.execute(
        text("INSERT INTO users (id, username, password_hash, role) VALUES (1, 'admin', 'x', 'admin')")
    )
    await db_session.execute(
        text(
            "INSERT INTO galleries (id, source, source_id, title, pages, visibility) "
            "VALUES (1, 'local', 'book', 'Book', 1, 'public')"
        )
    )
    await db_session.execute(
        text(
            "INSERT INTO blobs (sha256, file_size, extension, storage, external_path, ref_count) "
            "VALUES ('old-sha', :size, '.png', 'external', :path, 1)"
        ),
        {"size": input_path.stat().st_size, "path": str(input_path)},
    )
    await db_session.execute(
        text(
            "INSERT INTO images (id, gallery_id, page_num, filename, blob_sha256, visibility) "
            "VALUES (1, 1, 1, '001.png', 'old-sha', 'active')"
        )
    )
    await db_session.commit()

    async def fake_store_blob(path: Path, sha256: str, session):
        blob = Blob(
            sha256=sha256,
            file_size=path.stat().st_size,
            extension=path.suffix,
            storage="external",
            external_path=str(path),
            ref_count=0,
        )
        session.add(blob)
        await session.flush()
        return blob

    with (
        patch("worker.process.store_blob", side_effect=fake_store_blob),
        patch("worker.process.create_library_symlink", new_callable=AsyncMock),
    ):
        new_image_id = await _replace_processed_image(
            db_session,
            image_id=1,
            expected_sha256="old-sha",
            output_path=output_path,
            output_sha256="new-sha",
            width=8,
            height=10,
        )

    async with db_session_factory() as session:
        images = (await session.execute(select(Image).order_by(Image.id))).scalars().all()
        blobs = {row.sha256: row for row in (await session.execute(select(Blob))).scalars().all()}

    assert new_image_id == images[1].id
    assert len(images) == 2
    assert images[0].visibility == "replaced"
    assert images[0].replaced_by_image_id == images[1].id
    assert images[1].visibility == "active"
    assert images[1].page_num == 1
    assert blobs["old-sha"].ref_count == 1
    assert blobs[images[1].blob_sha256].ref_count == 1
