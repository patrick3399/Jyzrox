"""Regression: JXL bytes served under a `.jpg` name in a download staging dir.

Incident 2026-11-19 (Weibo `large` originals, gallery weibo/3944967175): the
importer counted them invalid; worker.download then deleted them and mis-parsed
`5251418014617671_01.jpg` as page 525141801461767101.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

JXL_BYTES = b"\xff\x0a" + b"\x00" * 64


def _make_importer():
    from worker.progressive import ProgressiveImporter

    importer = ProgressiveImporter(db_job_id=None, user_id=None)
    importer.gallery_id = 1
    importer.source = "weibo"
    importer.source_id = "3944967175"
    return importer


def _session_cm():
    session = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.get = AsyncMock(return_value=None)
    result = MagicMock()
    result.scalar_one_or_none.return_value = 7
    session.execute = AsyncMock(return_value=result)

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=cm)


async def _import_renamed(tmp_path: Path):
    importer = _make_importer()
    src = tmp_path / "5251418014617671_01.jpg"
    src.write_bytes(JXL_BYTES)
    store = AsyncMock(return_value=MagicMock())
    with (
        patch("worker.progressive.AsyncSessionLocal", _session_cm()),
        patch("worker.progressive.store_blob", store),
        patch("worker.progressive.increment_ref_count", AsyncMock()),
        patch("worker.progressive.create_library_symlink", AsyncMock()),
        patch.object(importer, "_publish_progress", AsyncMock()),
    ):
        await importer._import_single(src, 1, "a" * 64)
    return importer, src, store


async def test_progressive_import_renames_jxl_content_with_jpg_extension(tmp_path):
    """Weibo JXL under .jpg is renamed to .jxl in staging and stored as .jxl, not skipped invalid."""
    importer, src, store = await _import_renamed(tmp_path)

    new = tmp_path / "5251418014617671_01.jxl"
    assert not src.exists()
    assert new.exists()
    store.assert_awaited_once()
    assert store.await_args.args[0] == new
    assert importer.skipped_invalid_count == 0
    assert importer.has_processed(new) is True


async def test_staged_leftover_sweep_skips_renamed_jxl_file(tmp_path):
    """The post-run sweep must not hand the renamed .jxl to on_file a second time."""
    from worker.download import _import_staged_leftovers, _list_staged_media

    importer, _src, _store = await _import_renamed(tmp_path)
    new = tmp_path / "5251418014617671_01.jxl"
    # The sweep must actually see the .jxl (else skipping it proves nothing).
    assert new in _list_staged_media(tmp_path)

    on_file = AsyncMock()
    handed = await _import_staged_leftovers(importer, tmp_path, on_file)

    assert handed == 0
    on_file.assert_not_awaited()


def test_remove_corrupt_images_page_num_ignores_underscore_post_id(tmp_path):
    """`5251418014617671_01.jpg` is page 1 of a post, not page 525141801461767101."""
    from worker.download import _remove_corrupt_images

    (tmp_path / "5251418014617671_01.jpg").write_bytes(b"\x00\x01\x02\x03garbage")

    removed = _remove_corrupt_images(tmp_path)

    assert removed == [("5251418014617671_01.jpg", 1)]
