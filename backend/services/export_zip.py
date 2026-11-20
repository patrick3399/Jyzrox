"""Streamed ZIP_STORED archive helpers for gallery export."""

import zipfile
from dataclasses import dataclass
from pathlib import Path

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
