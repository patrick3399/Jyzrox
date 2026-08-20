"""Dataset export: stored bytes plus caption files, never a decode.

HR-007: the previous builder opened every source image at full resolution to
scale it, and a second time to probe bucket dimensions, on the process-wide
default executor with no admission bound. Four concurrent 178 MP decodes
measured 2578 MB anon against a 3 GB api limit. The export no longer decodes
at all, so the test asserts that directly.
"""

import zipfile

import PIL.Image as PILImage
import pytest

from services.dataset_export import (
    DatasetExportImage,
    DatasetExportOptions,
    build_dataset_archive,
    safe_component,
)


def _record(tmp_path, image_id=1, name="page.jpg", tags=("artist:someone",), caption=None):
    path = tmp_path / name
    path.write_bytes(b"not a real jpeg, and it never gets decoded")
    return DatasetExportImage(
        image_id=image_id,
        page_num=image_id,
        filename=name,
        sha256=f"{image_id:064x}",
        path=path,
        extension=".jpg",
        gallery_source="ehentai",
        gallery_source_id="123",
        gallery_source_url="https://e-hentai.org/g/123/abc",
        image_source_url=None,
        tags=tags,
        caption=caption,
    )


def _options(**overrides):
    base = {
        "dataset_name": "Test Dataset",
        "trigger_word": "",
        "validation_percent": 0,
        "include_metadata": True,
    }
    base.update(overrides)
    return DatasetExportOptions(**base)


def test_dataset_export_never_opens_a_source_image(tmp_path, monkeypatch):
    """The archive must be built without decoding anything (HR-007)."""

    def _fail_open(*args, **kwargs):
        raise AssertionError("dataset export opened an image")

    monkeypatch.setattr(PILImage, "open", _fail_open)

    archive_path = build_dataset_archive([_record(tmp_path)], _options())

    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
    assert any(name.endswith(".jpg") for name in names)


def test_dataset_export_writes_stored_bytes_unchanged(tmp_path):
    """Bytes go in as they are; trainers do their own resizing."""
    record = _record(tmp_path)
    original = record.path.read_bytes()

    archive_path = build_dataset_archive([record], _options())

    with zipfile.ZipFile(archive_path) as archive:
        image_name = next(n for n in archive.namelist() if n.endswith(".jpg"))
        assert archive.read(image_name) == original
        assert archive.getinfo(image_name).compress_type == zipfile.ZIP_STORED


def test_dataset_export_caption_uses_trigger_word_then_tags(tmp_path):
    archive_path = build_dataset_archive(
        [_record(tmp_path, tags=("artist:someone", "female:gloves"))],
        _options(trigger_word="alice_token"),
    )

    with zipfile.ZipFile(archive_path) as archive:
        caption_name = next(n for n in archive.namelist() if n.endswith(".txt"))
        assert archive.read(caption_name).decode() == "alice_token, gloves, someone"


def test_dataset_export_splits_validation_deterministically_by_sha(tmp_path):
    records = [_record(tmp_path, image_id=i, name=f"page{i}.jpg") for i in range(1, 21)]

    first = build_dataset_archive(records, _options(validation_percent=50))
    second = build_dataset_archive(records, _options(validation_percent=50))

    def _validation_names(path):
        with zipfile.ZipFile(path) as archive:
            return {n for n in archive.namelist() if n.startswith("images/validation/")}

    assert _validation_names(first) == _validation_names(second)


def test_dataset_export_excludes_unavailable_files_in_the_manifest(tmp_path):
    record = _record(tmp_path)
    record.path.unlink()

    archive_path = build_dataset_archive([record], _options())

    with zipfile.ZipFile(archive_path) as archive:
        manifest = archive.read("manifest.json").decode()
    assert '"status": "excluded"' in manifest
    assert '"reason": "unavailable"' in manifest


@pytest.mark.parametrize(
    ("value", "expected"),
    [("Alice / Bob", "Alice_Bob"), ("   ", "concept"), ("..hidden", "hidden")],
)
def test_safe_component_collapses_runs_of_unsafe_characters(value, expected):
    """The pattern ends in + so a run becomes one underscore, not one per char."""
    assert safe_component(value) == expected
