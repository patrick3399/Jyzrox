"""Training Data Export (Kohya format)."""

import asyncio
import json
import os
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from starlette.background import BackgroundTask

from core.auth import gallery_access_filter, require_role
from core.database import async_session
from db.models import Blob, Dataset, DatasetImage, Gallery, Image
from services.cas import resolve_blob_path
from services.dataset_export import DatasetExportImage, DatasetExportOptions, build_dataset_archive, safe_component

_SAFE_ARCNAME = re.compile(r"[^\w.\-]")

# ── Streamed ZIP_STORED archive ──────────────────────────────────────────
#
# The gallery export used to build the archive in a BytesIO and then hand it to
# StreamingResponse as iter([buf.getvalue()]) — getvalue() copies the whole
# buffer, so the archive and its copy were live at once. Against the endpoint's
# 2 GB source cap that approaches the api container's 4 GB limit; a 1048 MB
# gallery measured 1100.8 MB of unreclaimable anon.
#
# The contents are JPEG/PNG/WebP, already entropy-coded, so DEFLATE was earning
# 0.2% on a JPEG gallery and 0.0% on a PNG one for 40x the wall time. Dropping
# it to ZIP_STORED makes the archive size exactly computable up front, which is
# what lets the response keep a correct Content-Length while streaming.
_ZIP_LOCAL_HEADER_BYTES = 30
_ZIP_DATA_DESCRIPTOR_BYTES = 16
_ZIP_CENTRAL_HEADER_BYTES = 46
_ZIP_EOCD_BYTES = 22
# Past either limit zipfile emits ZIP64 records, which widen every header and
# invalidate the size arithmetic below.
_ZIP64_SIZE_LIMIT = 0xFFFFFFFF
_ZIP64_ENTRY_LIMIT = 0xFFFF
_COPY_CHUNK_BYTES = 64 * 1024


@dataclass(frozen=True)
class _ArchiveEntry:
    """One archive member: either a file to stream, or literal bytes."""

    arcname: str
    path: Path | None = None
    payload: bytes | None = None
    declared_size: int | None = None  # tests only; overrides the on-disk size

    @property
    def size(self) -> int:
        if self.declared_size is not None:
            return self.declared_size
        if self.payload is not None:
            return len(self.payload)
        return self.path.stat().st_size if self.path else 0


def _stored_zip_size(entries: list[_ArchiveEntry]) -> int:
    """Exact byte length of the archive :func:`_stream_stored_zip` will emit.

    Raises ``ValueError`` if the input would push zipfile into ZIP64, because
    the declared Content-Length would then be wrong — a worse failure than
    refusing, since the client would hang or truncate.
    """
    if len(entries) > _ZIP64_ENTRY_LIMIT:
        raise ValueError(f"archive needs ZIP64: {len(entries)} entries")
    total = _ZIP_EOCD_BYTES
    for entry in entries:
        size = entry.size
        if size > _ZIP64_SIZE_LIMIT:
            raise ValueError(f"archive needs ZIP64: {entry.arcname} is {size} bytes")
        name_bytes = len(entry.arcname.encode("utf-8"))
        total += _ZIP_LOCAL_HEADER_BYTES + name_bytes + size + _ZIP_DATA_DESCRIPTOR_BYTES
        total += _ZIP_CENTRAL_HEADER_BYTES + name_bytes
    if total > _ZIP64_SIZE_LIMIT:
        raise ValueError(f"archive needs ZIP64: {total} bytes total")
    return total


class _ChunkSink:
    """Non-seekable sink: zipfile then emits data descriptors instead of
    seeking back to patch local headers, so output can leave as it is produced."""

    def __init__(self) -> None:
        self._chunks: list[bytes] = []

    def write(self, data) -> int:
        self._chunks.append(bytes(data))
        return len(data)

    def flush(self) -> None:  # pragma: no cover - zipfile calls this on close
        pass

    def drain(self):
        while self._chunks:
            yield self._chunks.pop(0)


def _stream_stored_zip(entries: list[_ArchiveEntry]):
    """Yield the archive in chunks, holding at most one copy chunk at a time.

    Members are written through ``ZipFile.open(name, "w")`` rather than
    ``ZipFile.write(path)`` so a single large image cannot be buffered whole.
    """
    sink = _ChunkSink()
    with zipfile.ZipFile(sink, "w", zipfile.ZIP_STORED) as archive:
        for entry in entries:
            if entry.payload is not None:
                archive.writestr(entry.arcname, entry.payload)
                yield from sink.drain()
                continue
            if entry.path is None:  # pragma: no cover - defensive
                continue
            with archive.open(entry.arcname, "w") as destination, open(entry.path, "rb") as source:
                while chunk := source.read(_COPY_CHUNK_BYTES):
                    destination.write(chunk)
                    yield from sink.drain()
            yield from sink.drain()
    yield from sink.drain()


# Namespaces that are not trainable concepts and pollute captions
_DEFAULT_EXCLUDED_NAMESPACES = "rating,language,metadata"

# Formats kohya_ss / ai-toolkit / OneTrainer accept as training images
_TRAINABLE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}

router = APIRouter(tags=["export"])

_member = require_role("member")


@router.get("/dataset/{dataset_id}")
async def export_dataset(
    dataset_id: int,
    trigger_word: str = Query(default="", max_length=200),
    validation_percent: int = Query(default=0, ge=0, le=50),
    include_metadata: bool = True,
    auth: dict = Depends(_member),
):
    """Export a user-owned dataset as stored bytes plus caption files."""
    async with async_session() as session:
        dataset = (
            await session.execute(select(Dataset).where(Dataset.id == dataset_id, Dataset.user_id == auth["user_id"]))
        ).scalar_one_or_none()
        if dataset is None:
            raise HTTPException(status_code=404, detail="Dataset not found")
        rows = (
            await session.execute(
                select(Image, Gallery, Blob)
                .join(DatasetImage, DatasetImage.image_id == Image.id)
                .join(Gallery, Gallery.id == Image.gallery_id)
                .join(Blob, Blob.sha256 == Image.blob_sha256)
                .where(
                    DatasetImage.dataset_id == dataset_id,
                    DatasetImage.state == "included",
                    Image.visibility == "active",
                    gallery_access_filter(auth),
                )
                .order_by(Image.id)
            )
        ).all()

    if not rows:
        raise HTTPException(status_code=404, detail="Dataset has no included images")

    records = [
        DatasetExportImage(
            image_id=image.id,
            page_num=image.page_num,
            filename=image.filename or f"image_{image.id}{blob.extension}",
            sha256=blob.sha256,
            path=resolve_blob_path(blob, image.external_path),
            extension=blob.extension,
            gallery_source=gallery.source,
            gallery_source_id=gallery.source_id,
            gallery_source_url=gallery.source_url,
            image_source_url=image.source_item_url,
            tags=tuple(sorted(gallery.tags_array or [])),
            caption=image.caption,
        )
        for image, gallery, blob in rows
    ]
    options = DatasetExportOptions(
        dataset_name=dataset.name,
        trigger_word=trigger_word,
        validation_percent=validation_percent,
        include_metadata=include_metadata,
    )
    archive_path = await asyncio.to_thread(build_dataset_archive, records, options)
    filename = f"dataset_{dataset_id}_{safe_component(dataset.name)}.zip"
    return FileResponse(
        archive_path,
        media_type="application/zip",
        filename=filename,
        background=BackgroundTask(lambda: os.unlink(archive_path) if os.path.exists(archive_path) else None),
    )


def _caption_tags(
    tags: set[str],
    excluded_namespaces: frozenset[str],
    underscores_to_spaces: bool,
) -> list[str]:
    """Normalize raw 'namespace:name' tag strings into trainer caption tags.

    Strips namespace prefixes, drops excluded namespaces, optionally converts
    booru underscores to spaces, and returns a deterministically sorted list.
    """
    out: set[str] = set()
    for raw in tags:
        ns, sep, name = raw.partition(":")
        if not sep:
            ns, name = "", raw
        if ns in excluded_namespaces:
            continue
        tag = name.strip()
        if not tag:
            continue
        if underscores_to_spaces:
            tag = tag.replace("_", " ")
        out.add(tag)
    return sorted(out)


@router.get("/kohya/{gallery_id}")
async def export_kohya(
    gallery_id: int,
    exclude_namespaces: str = _DEFAULT_EXCLUDED_NAMESPACES,
    underscores_to_spaces: bool = False,
    auth: dict = Depends(_member),
):
    """Generates a zip file containing images and corresponding .txt files with tags."""
    excluded = frozenset(ns.strip() for ns in exclude_namespaces.split(",") if ns.strip())

    async with async_session() as session:
        # Get Gallery with access control
        gallery = (
            await session.execute(select(Gallery).where(Gallery.id == gallery_id, gallery_access_filter(auth)))
        ).scalar_one_or_none()
        if not gallery:
            raise HTTPException(status_code=404, detail="Gallery not found")

        gallery_tags = gallery.tags_array or []

        # Get Images with blobs eagerly loaded
        images = (
            (
                await session.execute(
                    select(Image)
                    .where(Image.gallery_id == gallery_id)
                    .order_by(Image.page_num.asc())
                    .options(selectinload(Image.blob))
                )
            )
            .scalars()
            .all()
        )

    if not images:
        raise HTTPException(status_code=404, detail="No images found in gallery")

    # Resolve filesystem paths via CAS
    def _file_path(img):
        if not img.blob:
            return None
        p = resolve_blob_path(img.blob, img.external_path)
        return p if p.exists() else None

    # Check total size before creating ZIP (limit: 2 GB)
    _MAX_ZIP_SIZE = 2 * 1024 * 1024 * 1024
    total_size = sum(img.blob.file_size for img in images if img.blob and img.blob.file_size)
    if total_size > _MAX_ZIP_SIZE:
        raise HTTPException(status_code=413, detail="Gallery too large to export (max 2 GB)")

    # Decide every archive member up front so the exact size can be declared
    # before a byte is produced (see _stored_zip_size).
    def _plan_entries() -> list[_ArchiveEntry]:
        entries: list[_ArchiveEntry] = []
        excluded_files: list[dict] = []
        used_arcnames: set[str] = set()
        for i, img in enumerate(images):
            file_path = _file_path(img)
            if not file_path:
                continue

            raw_name = img.filename if img.filename else f"image_{i}"

            ext = ((img.blob.extension if img.blob else None) or os.path.splitext(raw_name)[1]).lower()
            if ext not in _TRAINABLE_EXTS:
                excluded_files.append({"filename": raw_name, "reason": "unsupported_extension"})
                continue

            basename = _SAFE_ARCNAME.sub("_", os.path.basename(raw_name)) or f"image_{i}"
            page = img.page_num if img.page_num is not None else i + 1
            arcname = f"{page:04d}_{basename}"
            if arcname in used_arcnames:
                arcname = f"{page:04d}_{i}_{basename}"
            used_arcnames.add(arcname)

            entries.append(_ArchiveEntry(arcname=arcname, path=file_path))

            # Combine gallery tags and specific image tags
            all_tags = set(gallery_tags)
            if img.tags_array:
                all_tags.update(img.tags_array)

            base, _ = os.path.splitext(arcname)
            tag_string = ", ".join(_caption_tags(all_tags, excluded, underscores_to_spaces))
            entries.append(_ArchiveEntry(arcname=base + ".txt", payload=tag_string.encode("utf-8")))

        if excluded_files:
            entries.append(
                _ArchiveEntry(
                    arcname="manifest.json",
                    payload=json.dumps({"excluded": excluded_files}, indent=2).encode("utf-8"),
                )
            )
        return entries

    # Planning stats every source file, so keep it off the event loop (AIT-002).
    entries = await asyncio.to_thread(_plan_entries)
    try:
        content_length = _stored_zip_size(entries)
    except ValueError as exc:
        # Declaring a length that does not match the body would hang or truncate
        # the client, so refuse instead. Unreachable under the 2 GB cap above.
        raise HTTPException(status_code=413, detail=str(exc)) from exc

    return StreamingResponse(
        _stream_stored_zip(entries),
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename=gallery_{gallery_id}_kohya.zip",
            "Content-Length": str(content_length),
        },
    )
