"""
Regression tests for streaming the gallery export instead of buffering it.

The endpoint used to build the archive with ``BytesIO`` and hand it to
``StreamingResponse`` as ``iter([zip_buffer.getvalue()])``. ``getvalue()``
copies the whole buffer, so the archive and its copy were live at once. With
the endpoint's 2 GB source cap that approaches 4 GB — exactly the api
container's limit. Measured on a 1048 MB gallery: 1100.8 MB of unreclaimable
anon (a lower bound; an unsampled run of the same gallery recorded a 2007 MB
cgroup peak).

Two properties make the streamed replacement safe:

- ``ZIP_STORED`` makes the archive size exactly computable in advance, so the
  response still declares a correct ``Content-Length``. Compression was earning
  0.2% on JPEG and 0.0% on PNG galleries — these formats are already
  entropy-coded — while costing 40x the wall time.
- Writing through ``ZipFile.open(name, "w")`` in chunks bounds the buffer to a
  single copy chunk instead of a whole file, so one large image cannot spike
  memory.

A declared size that disagrees with the emitted body is worse than the original
bug: the client would hang or truncate. That invariant is pinned first.
"""

import io
import os
import zipfile
from pathlib import Path

import pytest


def _entry(tmp_path: Path, name: str, size: int):
    """An archive entry backed by a real file of `size` random bytes."""
    from routers.export import _ArchiveEntry

    p = tmp_path / name
    p.write_bytes(os.urandom(size))
    return _ArchiveEntry(arcname=name, path=p, payload=None)


def _text_entry(name: str, text: str):
    from routers.export import _ArchiveEntry

    return _ArchiveEntry(arcname=name, path=None, payload=text.encode("utf-8"))


class TestStoredZipSize:
    def test_declared_size_matches_streamed_bytes_exactly(self, tmp_path: Path) -> None:
        """Content-Length is computed before a single byte is produced.

        If it disagrees with the body the client hangs or truncates, so this is
        the load-bearing invariant of the whole approach.
        """
        from routers.export import _stored_zip_size, _stream_stored_zip

        entries = [
            _entry(tmp_path, "0001_page.jpg", 3000),
            _text_entry("0001_page.txt", "artist:bob, character:alice"),
            _entry(tmp_path, "0002_page.png", 17000),
            _text_entry("0002_page.txt", ""),
        ]

        declared = _stored_zip_size(entries)
        emitted = sum(len(chunk) for chunk in _stream_stored_zip(entries))

        assert declared == emitted

    def test_declared_size_matches_for_non_ascii_names(self, tmp_path: Path) -> None:
        """Names are length-counted as UTF-8 bytes, not characters.

        Real filenames in this library are routinely CJK, so a character-count
        would under-declare and truncate the response.
        """
        from routers.export import _stored_zip_size, _stream_stored_zip

        entries = [
            _entry(tmp_path, "0001_崩壞：星穹鐵道-阿格萊雅.jpg", 2048),
            _text_entry("0001_崩壞：星穹鐵道-阿格萊雅.txt", "tag"),
        ]

        declared = _stored_zip_size(entries)
        emitted = sum(len(chunk) for chunk in _stream_stored_zip(entries))

        assert declared == emitted

    def test_empty_entry_list_still_declares_a_valid_archive(self) -> None:
        """A gallery whose files have all gone missing still returns a real ZIP."""
        from routers.export import _stored_zip_size, _stream_stored_zip

        declared = _stored_zip_size([])
        body = b"".join(_stream_stored_zip([]))

        assert declared == len(body)
        with zipfile.ZipFile(io.BytesIO(body)) as zf:
            assert zf.namelist() == []


class TestStreamingShape:
    def test_archive_is_never_emitted_as_one_chunk(self, tmp_path: Path) -> None:
        """The exact regression: `iter([buf.getvalue()])` yielded everything at once."""
        from routers.export import _stream_stored_zip

        entries = [_entry(tmp_path, f"{i:04d}.bin", 300_000) for i in range(6)]

        chunks = list(_stream_stored_zip(entries))
        total = sum(len(c) for c in chunks)

        assert len(chunks) > 1, "the archive was produced in a single chunk"
        assert max(len(c) for c in chunks) < total, "one chunk held the entire archive"

    def test_buffer_stays_bounded_regardless_of_file_size(self, tmp_path: Path) -> None:
        """One large image must not be buffered whole.

        Writing via ZipFile.write() would accumulate an entire file before the
        caller could drain it; chunked ZipFile.open(name, "w") does not.
        """
        from routers.export import _COPY_CHUNK_BYTES, _stream_stored_zip

        big = 4_000_000
        entries = [_entry(tmp_path, "big.bin", big)]

        largest_chunk = max(len(c) for c in _stream_stored_zip(entries))

        assert largest_chunk < big / 4, (
            f"a {big} byte file produced a {largest_chunk} byte chunk; the whole file is being buffered"
        )
        # Allow ZIP framing on top of one copy chunk, but nothing file-sized.
        assert largest_chunk <= _COPY_CHUNK_BYTES * 2


class TestArchiveValidity:
    def test_streamed_archive_round_trips_byte_identical(self, tmp_path: Path) -> None:
        """Non-seekable output uses data descriptors; prove the result is readable."""
        from routers.export import _stream_stored_zip

        sources = {f"{i:04d}.bin": os.urandom(5000 + i * 111) for i in range(5)}
        entries = []
        for name, blob in sources.items():
            p = tmp_path / name
            p.write_bytes(blob)
            from routers.export import _ArchiveEntry

            entries.append(_ArchiveEntry(arcname=name, path=p, payload=None))
        entries.append(_text_entry("caption.txt", "artist:bob"))

        body = b"".join(_stream_stored_zip(entries))

        with zipfile.ZipFile(io.BytesIO(body)) as zf:
            assert zf.testzip() is None, "CRC mismatch in the streamed archive"
            for name, blob in sources.items():
                assert zf.read(name) == blob, f"{name} did not round-trip"
            assert zf.read("caption.txt") == b"artist:bob"
            # Data descriptors are what non-seekable output depends on.
            assert all(info.flag_bits & 0x08 for info in zf.infolist())

    def test_stored_entries_are_not_compressed(self, tmp_path: Path) -> None:
        """STORED is what makes the size predictable; DEFLATE would break it."""
        from routers.export import _stream_stored_zip

        entries = [_entry(tmp_path, "a.bin", 9000)]
        body = b"".join(_stream_stored_zip(entries))

        with zipfile.ZipFile(io.BytesIO(body)) as zf:
            info = zf.getinfo("a.bin")
            assert info.compress_type == zipfile.ZIP_STORED
            assert info.compress_size == info.file_size


class TestEndpointResponse:
    """End to end: the header the client actually receives must match the body."""

    async def test_response_declares_content_length_matching_the_body(
        self, client, db_session, db_session_factory, tmp_path: Path
    ) -> None:
        from unittest.mock import patch

        from tests.test_export import _insert_gallery, _insert_image

        gid = await _insert_gallery(db_session, title="Streamed Gallery", tags_array='["character:alice"]')
        for page in (1, 2, 3):
            image = tmp_path / f"page_{page:03d}.jpg"
            image.write_bytes(b"\xff\xd8\xff\xe0" + os.urandom(4000 + page))
            await _insert_image(
                db_session,
                gid,
                page_num=page,
                filename=image.name,
                file_path=str(image),
                tags_array='["artist:bob"]',
            )

        with patch("routers.export.async_session", db_session_factory):
            resp = await client.get(f"/api/export/kohya/{gid}")

        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/zip"
        declared = int(resp.headers["content-length"])
        assert declared == len(resp.content), "declared length disagrees with the streamed body"

        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            assert zf.testzip() is None
            assert "0001_page_001.jpg" in zf.namelist()
            assert "0001_page_001.txt" in zf.namelist()


class TestZip64Guard:
    def test_size_helper_refuses_input_that_would_switch_to_zip64(self, tmp_path: Path) -> None:
        """ZIP64 changes every header width, silently invalidating the prediction.

        The endpoint caps source data at 2 GB so this is unreachable today, but
        the helper must fail loudly rather than declare a wrong Content-Length
        if that cap ever moves.
        """
        from routers.export import _ArchiveEntry, _stored_zip_size

        oversized = _ArchiveEntry(arcname="huge.bin", path=None, payload=None, declared_size=0xFFFFFFFF + 1)

        with pytest.raises(ValueError, match="ZIP64"):
            _stored_zip_size([oversized])
