"""Dataset archive builder.

Writes the stored bytes as they are, plus one caption file per image. Nothing
here decodes an image: the previous version opened every source at full
resolution to scale it, and a second time to probe bucket dimensions, on the
process-wide default executor with no admission bound (HR-007). Trainers do
their own resizing and bucketing, so the decode bought nothing.
"""

import hashlib
import json
import os
import re
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

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
    caption: str | None


@dataclass(frozen=True)
class DatasetExportOptions:
    dataset_name: str
    trigger_word: str
    validation_percent: int
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


def build_dataset_archive(records: list[DatasetExportImage], options: DatasetExportOptions) -> str:
    """Build a ZIP on disk and return its temporary path.

    ZIP_STORED rather than DEFLATE: the members are JPEG/PNG/WebP, already
    entropy-coded, so compression earned a fraction of a percent for many times
    the wall time (the same measurement that drove 57225ec on the gallery side).
    """
    descriptor, output_path = tempfile.mkstemp(prefix="jyzrox-dataset-", suffix=".zip")
    os.close(descriptor)
    manifest: list[dict] = []

    try:
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_STORED, allowZip64=True) as archive:
            for index, record in enumerate(records):
                if record.extension.lower() not in _TRAINABLE_EXTS or not record.path.is_file():
                    manifest.append({"image_id": record.image_id, "status": "excluded", "reason": "unavailable"})
                    continue
                validation = _is_validation(record.sha256, options.validation_percent)
                root = "images/validation" if validation else "images/train"
                basename = safe_component(Path(record.filename).name, f"image_{record.image_id}")
                stem = f"{index + 1:05d}_{record.image_id}_{Path(basename).stem}"
                arcname = f"{root}/{stem}{record.extension.lower()}"

                archive.write(record.path, arcname)
                archive.writestr(
                    str(Path(arcname).with_suffix(".txt")),
                    _caption(record.tags, options.trigger_word, record.caption),
                )
                metadata = {
                    "image_id": record.image_id,
                    "sha256": record.sha256,
                    "split": "validation" if validation else "train",
                    "source": record.gallery_source,
                    "source_id": record.gallery_source_id,
                    "source_url": record.image_source_url or record.gallery_source_url,
                    "tags": list(record.tags),
                }
                manifest.append(metadata)
                if options.include_metadata:
                    archive.writestr(f"metadata/{stem}.json", json.dumps(metadata, ensure_ascii=False, indent=2))

            archive.writestr("manifest.json", json.dumps({"images": manifest}, ensure_ascii=False, indent=2))
        return output_path
    except Exception:
        Path(output_path).unlink(missing_ok=True)
        raise
