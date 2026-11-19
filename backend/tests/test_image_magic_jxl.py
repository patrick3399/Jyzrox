"""Regression: JPEG XL signatures in the image magic check.

Incident 2026-11-19 (gallery weibo/3944967175): Weibo served JPEG XL bytes
(`ff 0a` bare codestream) under `.jpg` names and the importer rejected them.
"""

from pathlib import Path

CONTAINER = b"\x00\x00\x00\x0cJXL \r\n\x87\n"
CODESTREAM = b"\xff\x0a"


def test_validate_image_magic_accepts_jxl_codestream(tmp_path: Path) -> None:
    """A bare-codestream JXL under its honest `.jxl` name is valid."""
    from services.image_magic import validate_image_magic

    f = tmp_path / "a.jxl"
    f.write_bytes(CODESTREAM + b"\x00" * 32)
    assert validate_image_magic(f) is True


def test_validate_image_magic_accepts_jxl_container(tmp_path: Path) -> None:
    """An ISO-BMFF JXL container under `.jxl` is valid."""
    from services.image_magic import validate_image_magic

    f = tmp_path / "a.jxl"
    f.write_bytes(CONTAINER + b"\x00" * 32)
    assert validate_image_magic(f) is True


def test_validate_image_magic_rejects_jxl_bytes_under_jpg_extension(tmp_path: Path) -> None:
    """Weibo JXL under `.jpg` stays invalid in the generic check (only staging renames it)."""
    from services.image_magic import validate_image_magic

    f = tmp_path / "5251418014617671_01.jpg"
    f.write_bytes(CODESTREAM + b"\x00" * 32)
    assert validate_image_magic(f) is False


def test_is_jxl_file_detects_both_signatures_and_rejects_jpeg(tmp_path: Path) -> None:
    """is_jxl_file sniffs content, not the extension, and does not match JPEG."""
    from services.image_magic import is_jxl_file

    stream = tmp_path / "s.jpg"
    stream.write_bytes(CODESTREAM + b"\x00" * 32)
    box = tmp_path / "b.jpg"
    box.write_bytes(CONTAINER + b"\x00" * 32)
    jpeg = tmp_path / "j.jpg"
    jpeg.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 32)

    assert is_jxl_file(stream) is True
    assert is_jxl_file(box) is True
    assert is_jxl_file(jpeg) is False
    assert is_jxl_file(tmp_path / "missing.jpg") is False
