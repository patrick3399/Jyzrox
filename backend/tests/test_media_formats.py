"""Regression coverage for the canonical media-format registry."""

from pathlib import Path

from services.media_formats import (
    IMAGE_EXTENSIONS,
    MEDIA_EXTENSIONS,
    VIDEO_EXTENSIONS,
    media_type_for_extension,
)


def test_mov_is_a_supported_video_everywhere():
    from core.watcher import _SUPPORTED_EXTS as watcher_extensions
    from plugins.builtin.fanbox.source import _VIDEO_EXTS as fanbox_video_extensions
    from routers.import_router import _SUPPORTED_EXTS as import_extensions
    from services.explorer_filesystem import MEDIA_EXTENSIONS as explorer_extensions
    from worker.constants import _MEDIA_EXTS, _VIDEO_EXTS
    from worker.scan import _SUPPORTED_MEDIA_EXTS as scan_extensions

    assert ".mov" in VIDEO_EXTENSIONS
    assert ".mov" in MEDIA_EXTENSIONS
    assert ".mov" in explorer_extensions
    assert ".mov" in watcher_extensions
    assert ".mov" in import_extensions
    assert ".mov" in scan_extensions
    assert ".mov" in fanbox_video_extensions
    assert ".mov" in _MEDIA_EXTS
    assert ".mov" in _VIDEO_EXTS
    assert media_type_for_extension(".mov") == "video"
    assert media_type_for_extension(Path("clip.MOV")) == "video"


def test_declared_formats_have_one_media_type():
    assert IMAGE_EXTENSIONS.isdisjoint(VIDEO_EXTENSIONS)
    assert MEDIA_EXTENSIONS == IMAGE_EXTENSIONS | VIDEO_EXTENSIONS
    assert all(media_type_for_extension(ext) is not None for ext in MEDIA_EXTENSIONS)


def test_unimplemented_container_formats_are_not_advertised():
    assert ".mkv" not in MEDIA_EXTENSIONS
    assert ".avi" not in MEDIA_EXTENSIONS
    assert media_type_for_extension(".mkv") is None


def test_gif_keeps_animated_image_media_type():
    assert media_type_for_extension(".gif") == "gif"
