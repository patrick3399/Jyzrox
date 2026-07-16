"""Trainer-ready dataset archive builders."""

import hashlib
import json
import os
import re
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image as PILImage

_SAFE_NAME = re.compile(r"[^\w.-]+")
_TRAINABLE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


@dataclass(frozen=True)
class DatasetExportImage:
    image_id: int
    page_num: int
    filename: str
    sha256: str
    path: Path
    extension: str
    gallery_source: str
    gallery_source_id: str
    gallery_source_url: str | None
    image_source_url: str | None
    tags: tuple[str, ...]
    original_tags: tuple[str, ...]
    caption: str | None
    tag_confidence: dict[str, float | None]


@dataclass(frozen=True)
class DatasetExportOptions:
    preset: str
    dataset_name: str
    trigger_word: str
    repeats: int
    validation_percent: int
    resolution: int | None
    precompute_buckets: bool
    include_metadata: bool


def safe_component(value: str, fallback: str = "concept") -> str:
    return (_SAFE_NAME.sub("_", value.strip()).strip("._") or fallback)[:100]


def _is_validation(sha256: str, validation_percent: int) -> bool:
    if validation_percent <= 0:
        return False
    digest = hashlib.sha256(sha256.encode()).digest()
    return int.from_bytes(digest[:4], "big") % 100 < validation_percent


def _caption(tags: tuple[str, ...], trigger_word: str, natural_caption: str | None) -> str:
    if natural_caption:
        return f"{trigger_word.strip()}, {natural_caption}" if trigger_word.strip() else natural_caption
    normalized = sorted({tag.partition(":")[2] or tag for tag in tags if tag.strip()})
    if trigger_word.strip():
        normalized.insert(0, trigger_word.strip())
    return ", ".join(dict.fromkeys(normalized))


def _write_scaled_image(
    archive: zipfile.ZipFile, record: DatasetExportImage, arcname: str, resolution: int
) -> tuple[int, int]:
    with PILImage.open(record.path) as image:
        image.thumbnail((resolution, resolution), PILImage.Resampling.LANCZOS)
        width, height = image.size
        with tempfile.SpooledTemporaryFile(max_size=16 * 1024 * 1024) as output:
            suffix = record.extension.lower()
            image_format = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP"}[suffix]
            if image_format == "JPEG" and image.mode not in {"RGB", "L"}:
                image = image.convert("RGB")
            image.save(output, format=image_format, quality=95)
            output.seek(0)
            archive.writestr(arcname, output.read())
    return width, height


def _kohya_config(options: DatasetExportOptions, train_dir: str, validation_dir: str | None) -> str:
    resolution = options.resolution or 1024
    lines = [
        "[general]",
        'caption_extension = ".txt"',
        "shuffle_caption = true",
        "",
        "[[datasets]]",
        f"resolution = {resolution}",
        f"enable_bucket = {str(options.precompute_buckets).lower()}",
        "",
        "[[datasets.subsets]]",
        f"image_dir = {json.dumps(train_dir)}",
        f"num_repeats = {options.repeats}",
    ]
    if validation_dir:
        lines.extend(
            [
                "",
                "[[datasets.subsets]]",
                f"image_dir = {json.dumps(validation_dir)}",
                "num_repeats = 1",
                "is_reg = true",
            ]
        )
    return "\n".join(lines) + "\n"


def _ai_toolkit_config(options: DatasetExportOptions) -> str:
    resolution = options.resolution or 1024
    name = safe_component(options.dataset_name, "jyzrox_dataset")
    return (
        "job: extension\n"
        "config:\n"
        f"  name: {json.dumps(name)}\n"
        "  process:\n"
        "    - type: sd_trainer\n"
        "      training_folder: output\n"
        "      datasets:\n"
        "        - folder_path: images/train\n"
        "          caption_ext: txt\n"
        f"          resolution: [{resolution}]\n"
        f"          num_repeats: {options.repeats}\n"
    )


def build_dataset_archive(records: list[DatasetExportImage], options: DatasetExportOptions) -> str:
    """Build a ZIP on disk and return its temporary path."""
    descriptor, output_path = tempfile.mkstemp(prefix="jyzrox-dataset-", suffix=".zip")
    os.close(descriptor)
    concept = safe_component(options.trigger_word or options.dataset_name)
    kohya_train_dir = f"train/{options.repeats}_{concept}"
    kohya_validation_dir = f"validation/1_{concept}" if options.validation_percent else None
    manifest: list[dict] = []

    try:
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
            for index, record in enumerate(records):
                if record.extension.lower() not in _TRAINABLE_EXTS or not record.path.is_file():
                    manifest.append({"image_id": record.image_id, "status": "excluded", "reason": "unavailable"})
                    continue
                validation = _is_validation(record.sha256, options.validation_percent)
                if options.preset == "kohya":
                    root = kohya_validation_dir if validation else kohya_train_dir
                else:
                    root = "images/validation" if validation else "images/train"
                basename = safe_component(Path(record.filename).name, f"image_{record.image_id}")
                stem = f"{index + 1:05d}_{record.image_id}_{Path(basename).stem}"
                extension = record.extension.lower()
                image_name = f"{stem}{extension}"
                preliminary = f"{root}/{image_name}"

                width = height = None
                if options.resolution:
                    if options.precompute_buckets:
                        with PILImage.open(record.path) as probe:
                            probe.thumbnail((options.resolution, options.resolution))
                            bucket = f"{max(64, round(probe.width / 64) * 64)}x{max(64, round(probe.height / 64) * 64)}"
                        preliminary = f"{root}/buckets/{bucket}/{image_name}"
                    width, height = _write_scaled_image(archive, record, preliminary, options.resolution)
                else:
                    archive.write(record.path, preliminary)

                caption_name = str(Path(preliminary).with_suffix(".txt"))
                archive.writestr(caption_name, _caption(record.tags, options.trigger_word, record.caption))
                metadata = {
                    "image_id": record.image_id,
                    "sha256": record.sha256,
                    "split": "validation" if validation else "train",
                    "source": record.gallery_source,
                    "source_id": record.gallery_source_id,
                    "source_url": record.image_source_url or record.gallery_source_url,
                    "original_tags": list(record.original_tags),
                    "tag_confidence": record.tag_confidence,
                    "output_width": width,
                    "output_height": height,
                }
                manifest.append(metadata)
                if options.include_metadata:
                    archive.writestr(f"metadata/{stem}.json", json.dumps(metadata, ensure_ascii=False, indent=2))

            if options.preset == "kohya":
                archive.writestr(
                    "dataset.toml",
                    _kohya_config(options, kohya_train_dir, kohya_validation_dir),
                )
            else:
                archive.writestr("config.yaml", _ai_toolkit_config(options))
            archive.writestr("manifest.json", json.dumps({"images": manifest}, ensure_ascii=False, indent=2))
        return output_path
    except Exception:
        Path(output_path).unlink(missing_ok=True)
        raise
