"""
Regression tests for recovery of local imports stranded by worker death (HR-019).

Incident 2026-08-13: a container OOM kill (SIGKILL) killed local_import_job
mid-transaction for galleries 524205/524207/524208/524209. They stayed on
`download_status='importing'` with `pages = NULL` indefinitely, because
`auto_discover_job` skips any `(source, source_id)` that already exists and
`rescan_library_job` rewrites `gallery.pages` only inside its `if removed:`
branch, which cannot run for a gallery that has no images yet.

SIGKILL cannot be intercepted in-process, so no `except` clause reaches the
terminal-status write. Recovery has to happen out of band, which is what
`requeue_orphaned_imports` does at worker startup.
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text

_INSERT = (
    "INSERT INTO galleries "
    "(source, source_id, title, download_status, pages, import_mode, source_path, "
    " deleted_at, tags_array) "
    "VALUES ('local', :source_id, :title, :status, :pages, 'link', :source_path, "
    " :deleted_at, '[]')"
)


@asynccontextmanager
async def _session_ctx(session):
    yield session


async def _seed(
    db_session,
    *,
    source_id: str,
    status: str = "importing",
    pages=None,
    source_path: str | None = "/mnt/ssd-data/images/omochi/x",
    deleted_at=None,
) -> int:
    await db_session.execute(
        text(_INSERT),
        {
            "source_id": source_id,
            "title": source_id,
            "status": status,
            "pages": pages,
            "source_path": source_path,
            "deleted_at": deleted_at,
        },
    )
    await db_session.commit()
    row = await db_session.execute(text("SELECT id FROM galleries WHERE source_id = :s"), {"s": source_id})
    return row.scalar_one()


async def _run(db_session):
    """Run the sweeper against the test DB, capturing enqueue calls."""
    from worker import import_recovery

    enqueued: list[tuple[str, dict]] = []

    async def _fake_enqueue(job_name, **kwargs):
        enqueued.append((job_name, kwargs))

    with (
        patch.object(import_recovery, "AsyncSessionLocal", lambda: _session_ctx(db_session)),
        patch("core.queue.enqueue", AsyncMock(side_effect=_fake_enqueue)),
    ):
        result = await import_recovery.requeue_orphaned_imports({})
    return result, enqueued


class TestRequeueOrphanedImports:
    async def test_requeues_gallery_left_importing_with_null_pages(self, db_session):
        """The exact state a SIGKILL leaves behind: importing, no pages, no retry."""
        gallery_id = await _seed(db_session, source_id="omochi/stranded")

        result, enqueued = await _run(db_session)

        assert result["requeued"] == 1
        assert result["gallery_ids"] == [gallery_id]
        assert len(enqueued) == 1
        job_name, kwargs = enqueued[0]
        assert job_name == "local_import_job"
        assert kwargs["gallery_id"] == gallery_id
        assert kwargs["source_dir"] == "/mnt/ssd-data/images/omochi/x"
        assert kwargs["mode"] == "link"
        # Shared-wrapper timeout, matching every other local_import_job enqueue.
        assert kwargs["_timeout"] == 3600
        # SAQ deduplicates on this key, so replaying recovery is idempotent.
        assert kwargs["_job_id"] == f"local-import:{gallery_id}"

    async def test_does_not_requeue_trashed_gallery(self, db_session):
        """HR-014: recovery must never resurrect a trashed gallery.

        A gallery can be trashed while its import job is still queued, so the
        stranded-import state and `deleted_at` can legitimately coexist.
        """
        await _seed(
            db_session,
            source_id="omochi/trashed",
            deleted_at="2026-08-13 00:00:00+00",
        )

        result, enqueued = await _run(db_session)

        assert result["requeued"] == 0
        assert enqueued == []

    async def test_does_not_requeue_completed_gallery(self, db_session):
        """Only galleries still claiming `importing` are orphans."""
        await _seed(db_session, source_id="omochi/done", status="complete", pages=24)

        result, enqueued = await _run(db_session)

        assert result["requeued"] == 0
        assert enqueued == []

    async def test_does_not_requeue_gallery_without_source_path(self, db_session):
        """Without a source directory there is nothing to re-import from."""
        await _seed(db_session, source_id="omochi/nopath", source_path=None)

        result, enqueued = await _run(db_session)

        assert result["requeued"] == 0
        assert enqueued == []

    async def test_requeues_only_the_orphans_in_a_mixed_library(self, db_session):
        """A real library holds all of these at once; only the orphan may move."""
        stranded = await _seed(db_session, source_id="omochi/mixed-stranded")
        await _seed(db_session, source_id="omochi/mixed-done", status="complete", pages=12)
        await _seed(db_session, source_id="omochi/mixed-trashed", deleted_at="2026-08-13 00:00:00+00")
        await _seed(db_session, source_id="omochi/mixed-nopath", source_path=None)

        result, enqueued = await _run(db_session)

        assert result["gallery_ids"] == [stranded]
        assert [kwargs["gallery_id"] for _, kwargs in enqueued] == [stranded]


class TestLocalImportTerminalStatus:
    """The in-process half: failures Python *can* observe must not stay `importing`."""

    async def test_unexpected_error_leaves_failed_not_importing(self, tmp_path, db_session):
        """A non-source-change exception must still write a terminal status.

        Before this guard only SourceDirectoryChangedError / SourceFileChangedError
        were handled, so e.g. a LibraryDirCollisionError or an OSError while
        hashing left the row on `importing` forever. Link mode no longer hashes
        in this job (ADR 0015), so the guard is exercised through copy mode.
        """
        from worker import importer

        source_dir = tmp_path / "gallery"
        source_dir.mkdir()
        (source_dir / "001.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 64)

        gallery_id = await _seed(db_session, source_id="omochi/boom", source_path=str(source_dir))

        redis = AsyncMock()
        redis.setex = AsyncMock(return_value=True)

        with (
            patch.object(importer, "AsyncSessionLocal", lambda: _session_ctx(db_session)),
            patch.object(importer, "_validate_image_magic", return_value=True),
            patch.object(
                importer,
                "hash_file_with_identity",
                side_effect=RuntimeError("library directory collision"),
            ),
        ):
            with pytest.raises(RuntimeError):
                await importer.local_import_job({"redis": redis}, str(source_dir), "copy", gallery_id)

        status = (
            await db_session.execute(text("SELECT download_status FROM galleries WHERE id = :i"), {"i": gallery_id})
        ).scalar_one()
        assert status == "failed", "an unhandled import failure must not stay on 'importing'"


async def _seed_page(db_session, gallery_id: int, *, sha: str | None = None) -> None:
    await db_session.execute(
        text(
            "INSERT INTO images (gallery_id, page_num, filename, blob_sha256, external_path) "
            "VALUES (:gid, 1, 'a.jpg', :sha, '/mnt/lib/a.jpg')"
        ),
        {"gid": gallery_id, "sha": sha},
    )
    await db_session.commit()


class TestRequeueStrandedLinkHash:
    async def test_gallery_with_pending_pages_gets_a_hash_job_after_restart(self, db_session):
        """A link_hash_job killed with the worker leaves a non-importing gallery with pending pages."""
        stranded = await _seed(db_session, source_id="omochi/pending", status="complete", pages=1)
        await _seed_page(db_session, stranded)
        done = await _seed(db_session, source_id="omochi/hashed", status="complete", pages=1)
        await db_session.execute(
            text(
                "INSERT INTO blobs (sha256, file_size, media_type, extension, storage) VALUES ('h', 1, 'image', '.jpg', 'external')"
            )
        )
        await _seed_page(db_session, done, sha="h")
        trashed = await _seed(
            db_session, source_id="omochi/pending-trashed", status="complete", deleted_at="2026-08-13 00:00:00+00"
        )
        await _seed_page(db_session, trashed)
        importing = await _seed(db_session, source_id="omochi/pending-importing")
        await _seed_page(db_session, importing)

        result, enqueued = await _run(db_session)

        hash_jobs = [kwargs for name, kwargs in enqueued if name == "link_hash_job"]
        assert [kwargs["gallery_id"] for kwargs in hash_jobs] == [stranded]
        assert hash_jobs[0]["_job_id"] == f"link-hash:{stranded}"
        assert result["link_hash_requeued"] == 1
        # The importing gallery goes through the import replay, which syncs and queues the hash itself.
        assert [kwargs["gallery_id"] for name, kwargs in enqueued if name == "local_import_job"] == [importing]
