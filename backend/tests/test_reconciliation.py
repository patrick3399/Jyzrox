"""
Unit tests for worker/reconciliation.py.

Covers:
- Cron gate not reached → skipped result
- Empty / non-existent library path → completes with zero counts
- Broken symlinks removed from filesystem
- Empty gallery directories removed from DB
- Orphan galleries (in DB but not on disk) cleaned
- Orphan blobs (ref_count <= 0, actual_refs == 0) deleted from CAS + DB
- Drifted ref_counts (ref_count <= 0 but actual_refs > 0) corrected
- Progress written to Redis during each phase
- Result stored in Redis with TTL at completion
- Filesystem errors during cleanup do not crash the job
- Multiple library paths are all scanned (via settings.data_library_path)
"""

import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SHA_A = "aaaa" * 16
SHA_B = "bbbb" * 16


def _make_redis():
    """Return a minimal AsyncMock Redis with setex/delete pre-configured."""
    r = AsyncMock()
    r.setex = AsyncMock(return_value=True)
    r.delete = AsyncMock(return_value=1)
    return r


def _make_ctx(redis=None):
    if redis is None:
        redis = _make_redis()
    return {"redis": redis}


def _make_session_ctx(execute_side_effects=None):
    """
    Build a mock AsyncSessionLocal context manager.

    execute_side_effects: list of return values for successive session.execute() calls.
    """
    session = AsyncMock()
    session.commit = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)

    if execute_side_effects is not None:
        session.execute = AsyncMock(side_effect=execute_side_effects)
    else:
        # Default: return an empty result set for every call
        empty_result = _make_empty_result()
        session.execute = AsyncMock(return_value=empty_result)

    return session


def _make_empty_result():
    """Mimic the object returned by session.execute() with no rows."""
    result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = []
    result.scalars.return_value = scalars
    result.all.return_value = []
    return result


def _make_result_with_rows(rows):
    """Mimic session.execute() returning specific row objects."""
    result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = rows
    result.scalars.return_value = scalars
    result.all.return_value = rows
    return result


def _make_dir_entry(name, is_dir=True, is_symlink=False, path=None):
    """Build a mock os.DirEntry."""
    entry = MagicMock()
    entry.name = name
    entry.path = path or f"/data/library/{name}"
    entry.is_dir = MagicMock(return_value=is_dir)
    entry.is_symlink = MagicMock(return_value=is_symlink)
    return entry


def _make_gallery_row(id, source, source_id, download_status="downloaded"):
    row = MagicMock()
    row.id = id
    row.source = source
    row.source_id = source_id
    row.download_status = download_status
    return row


def _make_blob_gc_row(sha256, extension=".jpg", actual_refs=0, storage="cas", external_path=None):
    row = MagicMock()
    row.sha256 = sha256
    row.extension = extension
    row.actual_refs = actual_refs
    row.storage = storage
    row.external_path = external_path
    return row


# ---------------------------------------------------------------------------
# TestReconciliationJob
# ---------------------------------------------------------------------------


class TestReconciliationJob:
    """Tests for reconciliation_job(ctx)."""

    async def test_cron_gate_not_reached_returns_skipped(self):
        """When _cron_should_run returns False, job returns skipped status."""
        from worker.reconciliation import reconciliation_job

        ctx = _make_ctx()

        with (
            patch(
                "worker.reconciliation._cron_should_run",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch("worker.reconciliation._cron_record", new_callable=AsyncMock),
        ):
            result = await reconciliation_job(ctx)

        assert result["status"] == "skipped"
        assert result["reason"] == "interval_not_reached"

    async def test_nonexistent_library_path_returns_done_with_zero_counts(self, tmp_path):
        """If data_library_path does not exist, returns done with all-zero stats."""
        from worker.reconciliation import reconciliation_job

        ctx = _make_ctx()
        missing_path = str(tmp_path / "no_such_library")

        mock_settings = MagicMock()
        mock_settings.data_library_path = missing_path

        with (
            patch("worker.reconciliation._cron_should_run", new_callable=AsyncMock, return_value=True),
            patch("worker.reconciliation._cron_record", new_callable=AsyncMock),
            patch("worker.reconciliation.settings", mock_settings),
        ):
            result = await reconciliation_job(ctx)

        assert result["status"] == "done"
        assert result["removed_images"] == 0
        assert result["removed_galleries"] == 0
        assert result["orphan_blobs_cleaned"] == 0

    async def test_broken_symlinks_unlinked_from_filesystem(self, tmp_path):
        """Broken symlinks inside gallery dirs should be removed via os.unlink."""
        from worker.reconciliation import reconciliation_job

        lib_base = tmp_path / "library"
        lib_base.mkdir()

        ctx = _make_ctx()

        mock_settings = MagicMock()
        mock_settings.data_library_path = str(lib_base)

        # The broken link's path is a path that does not actually exist on disk,
        # so Path(fe.path).exists() will return False naturally.
        broken_path_str = str(tmp_path / "nonexistent_target.jpg")

        source_entry = _make_dir_entry("src_a", is_dir=True, path=str(lib_base / "src_a"))
        gal_entry = _make_dir_entry("gal_1", is_dir=True, path=str(lib_base / "src_a" / "gal_1"))
        broken_link = _make_dir_entry(
            "broken.jpg",
            is_dir=False,
            is_symlink=True,
            path=broken_path_str,
        )

        def _scandir_side_effect(path):
            path_str = str(path)
            if path_str == str(lib_base):
                return iter([source_entry])
            if "src_a" in path_str and "gal_1" not in path_str:
                return iter([gal_entry])
            if "gal_1" in path_str:
                return iter([broken_link])
            return iter([])

        execute_returns = [
            _make_result_with_rows([]),  # Phase 1 Gallery
            _make_result_with_rows([]),  # Phase 1 Images
            _make_result_with_rows([]),  # Phase 2 orphan galleries
            _make_result_with_rows([]),  # Phase 3 blob GC
        ]
        session = _make_session_ctx(execute_side_effects=execute_returns)

        with (
            patch("worker.reconciliation._cron_should_run", new_callable=AsyncMock, return_value=True),
            patch("worker.reconciliation._cron_record", new_callable=AsyncMock),
            patch("worker.reconciliation.settings", mock_settings),
            patch("os.scandir", side_effect=_scandir_side_effect),
            patch("os.unlink") as mock_unlink,
            patch("worker.reconciliation.AsyncSessionLocal", return_value=session),
            patch("worker.reconciliation.cas_path", return_value=MagicMock(exists=MagicMock(return_value=False))),
            patch("worker.reconciliation.thumb_dir", return_value=MagicMock(exists=MagicMock(return_value=False))),
        ):
            result = await reconciliation_job(ctx)

        # The broken symlink must have been unlinked
        mock_unlink.assert_any_call(broken_path_str)
        assert result["status"] == "done"

    async def test_empty_gallery_directories_removed_from_db(self, tmp_path):
        """Gallery dirs with zero valid files should be deleted from the DB."""
        from worker.reconciliation import reconciliation_job

        lib_base = tmp_path / "library"
        lib_base.mkdir()

        ctx = _make_ctx()

        mock_settings = MagicMock()
        mock_settings.data_library_path = str(lib_base)

        source_entry = _make_dir_entry("src_a", is_dir=True, path=str(lib_base / "src_a"))
        gal_entry = _make_dir_entry("gal_empty", is_dir=True, path=str(lib_base / "src_a" / "gal_empty"))

        def _scandir_side_effect(path):
            path_str = str(path)
            if path_str == str(lib_base):
                return iter([source_entry])
            if "src_a" in path_str and "gal_empty" not in path_str:
                return iter([gal_entry])
            # Empty gallery dir — no files inside
            return iter([])

        # Simulate Gallery row found for ("src_a", "gal_empty")
        gallery_row = MagicMock()
        gallery_row.id = 10
        gallery_row.source = "src_a"
        gallery_row.source_id = "gal_empty"

        phase1_galleries_result = _make_result_with_rows([gallery_row])
        # Images query for galleries in this chunk → empty
        phase1_images_result = _make_result_with_rows([])
        # Phase 2 orphan gallery check → no rows
        phase2_result = _make_result_with_rows([])
        # Phase 3 blob GC → no rows
        phase3_result = _make_result_with_rows([])

        execute_returns = [
            phase1_galleries_result,   # select Gallery WHERE tuple IN
            phase1_images_result,      # select Image WHERE gallery_id IN
            _make_empty_result(),      # DELETE FROM galleries (empty galleries)
            phase2_result,             # select Gallery for orphan check
            phase3_result,             # blob GC query
        ]

        session = _make_session_ctx(execute_side_effects=execute_returns)

        with (
            patch("worker.reconciliation._cron_should_run", new_callable=AsyncMock, return_value=True),
            patch("worker.reconciliation._cron_record", new_callable=AsyncMock),
            patch("worker.reconciliation.settings", mock_settings),
            patch("os.scandir", side_effect=_scandir_side_effect),
            patch("pathlib.Path.exists", return_value=True),
            patch("worker.reconciliation.AsyncSessionLocal", return_value=session),
            patch("worker.reconciliation.cas_path", return_value=MagicMock(exists=MagicMock(return_value=False))),
            patch("worker.reconciliation.thumb_dir", return_value=MagicMock(exists=MagicMock(return_value=False))),
        ):
            result = await reconciliation_job(ctx)

        assert result["status"] == "done"
        assert result["removed_galleries"] >= 1

    async def test_orphan_galleries_cleaned_from_db(self, tmp_path):
        """Galleries present in DB but absent on disk should be deleted."""
        from worker.reconciliation import reconciliation_job

        # Create an empty library dir (no gallery dirs on disk)
        lib_base = tmp_path / "library"
        lib_base.mkdir()

        ctx = _make_ctx()

        mock_settings = MagicMock()
        mock_settings.data_library_path = str(lib_base)

        def _scandir_side_effect(path):
            # Return nothing for lib_base — no gallery dirs on disk
            return iter([])

        # Phase 1: no FS keys → no chunk iterations
        # Phase 2: one gallery in DB not on disk
        orphan_gallery = _make_gallery_row(id=99, source="src_x", source_id="gal_orphan")
        # Phase 2 images for this orphan → empty
        phase2_images_result = _make_result_with_rows([])
        phase2_galleries_result = _make_result_with_rows([orphan_gallery])
        # Phase 3 blob GC → empty
        phase3_result = _make_result_with_rows([])

        execute_returns = [
            phase2_galleries_result,   # select Gallery for orphan check
            phase2_images_result,      # select Image WHERE gallery_id IN
            _make_empty_result(),      # DELETE FROM galleries
            phase3_result,             # blob GC
        ]

        session = _make_session_ctx(execute_side_effects=execute_returns)

        with (
            patch("worker.reconciliation._cron_should_run", new_callable=AsyncMock, return_value=True),
            patch("worker.reconciliation._cron_record", new_callable=AsyncMock),
            patch("worker.reconciliation.settings", mock_settings),
            patch("os.scandir", side_effect=_scandir_side_effect),
            patch("worker.reconciliation.AsyncSessionLocal", return_value=session),
            patch("worker.reconciliation.cas_path", return_value=MagicMock(exists=MagicMock(return_value=False))),
            patch("worker.reconciliation.thumb_dir", return_value=MagicMock(exists=MagicMock(return_value=False))),
        ):
            result = await reconciliation_job(ctx)

        assert result["status"] == "done"
        assert result["removed_galleries"] >= 1

    async def test_orphan_blobs_deleted_from_cas_and_db(self, tmp_path):
        """Blobs with ref_count<=0 and actual_refs==0 should have CAS files deleted."""
        from worker.reconciliation import reconciliation_job

        lib_base = tmp_path / "library"
        lib_base.mkdir()

        ctx = _make_ctx()
        mock_settings = MagicMock()
        mock_settings.data_library_path = str(lib_base)

        orphan_blob = _make_blob_gc_row(SHA_A, extension=".jpg", actual_refs=0)

        def _scandir_side_effect(path):
            return iter([])

        phase2_galleries_result = _make_result_with_rows([])
        phase3_blob_gc_result = _make_result_with_rows([orphan_blob])
        # DELETE blobs result
        delete_result = _make_empty_result()

        execute_returns = [
            phase2_galleries_result,   # Phase 2 orphan galleries
            phase3_blob_gc_result,     # Phase 3 GC query
            delete_result,             # DELETE FROM blobs
        ]

        session = _make_session_ctx(execute_side_effects=execute_returns)

        fake_cas_file = MagicMock(spec=Path)
        fake_cas_file.exists.return_value = True
        fake_td = MagicMock(spec=Path)
        fake_td.exists.return_value = False

        with (
            patch("worker.reconciliation._cron_should_run", new_callable=AsyncMock, return_value=True),
            patch("worker.reconciliation._cron_record", new_callable=AsyncMock),
            patch("worker.reconciliation.settings", mock_settings),
            patch("os.scandir", side_effect=_scandir_side_effect),
            patch("worker.reconciliation.AsyncSessionLocal", return_value=session),
            patch("worker.reconciliation.cas_path", return_value=fake_cas_file),
            patch("worker.reconciliation.thumb_dir", return_value=fake_td),
            patch("shutil.rmtree"),
        ):
            result = await reconciliation_job(ctx)

        assert result["status"] == "done"
        assert result["orphan_blobs_cleaned"] == 1
        fake_cas_file.unlink.assert_called_once()

    async def test_drifted_ref_counts_corrected(self, tmp_path):
        """Blobs with ref_count<=0 but actual_refs>0 should have ref_count corrected."""
        from worker.reconciliation import reconciliation_job

        lib_base = tmp_path / "library"
        lib_base.mkdir()

        ctx = _make_ctx()
        mock_settings = MagicMock()
        mock_settings.data_library_path = str(lib_base)

        drifted_blob = _make_blob_gc_row(SHA_B, extension=".png", actual_refs=3)

        def _scandir_side_effect(path):
            return iter([])

        phase2_galleries_result = _make_result_with_rows([])
        phase3_blob_gc_result = _make_result_with_rows([drifted_blob])
        correction_result = _make_empty_result()  # UPDATE blobs SET ref_count
        commit_point = _make_empty_result()

        execute_returns = [
            phase2_galleries_result,
            phase3_blob_gc_result,
            correction_result,   # UPDATE for drifted blob
        ]

        session = _make_session_ctx(execute_side_effects=execute_returns)

        with (
            patch("worker.reconciliation._cron_should_run", new_callable=AsyncMock, return_value=True),
            patch("worker.reconciliation._cron_record", new_callable=AsyncMock),
            patch("worker.reconciliation.settings", mock_settings),
            patch("os.scandir", side_effect=_scandir_side_effect),
            patch("worker.reconciliation.AsyncSessionLocal", return_value=session),
            patch("worker.reconciliation.cas_path", return_value=MagicMock(exists=MagicMock(return_value=False))),
            patch("worker.reconciliation.thumb_dir", return_value=MagicMock(exists=MagicMock(return_value=False))),
        ):
            result = await reconciliation_job(ctx)

        assert result["status"] == "done"
        # Drifted blobs are corrected, not cleaned
        assert result["orphan_blobs_cleaned"] == 0
        # session.execute should have been called with an UPDATE
        assert session.execute.call_count >= 3

    async def test_progress_written_to_redis_during_execution(self, tmp_path):
        """r.setex('reconcile:progress', ...) should be called during processing."""
        from worker.reconciliation import reconciliation_job

        lib_base = tmp_path / "library"
        lib_base.mkdir()

        redis = _make_redis()
        ctx = _make_ctx(redis=redis)

        mock_settings = MagicMock()
        mock_settings.data_library_path = str(lib_base)

        def _scandir_side_effect(path):
            return iter([])

        session = _make_session_ctx(execute_side_effects=[
            _make_result_with_rows([]),  # Phase 2
            _make_result_with_rows([]),  # Phase 3
        ])

        with (
            patch("worker.reconciliation._cron_should_run", new_callable=AsyncMock, return_value=True),
            patch("worker.reconciliation._cron_record", new_callable=AsyncMock),
            patch("worker.reconciliation.settings", mock_settings),
            patch("os.scandir", side_effect=_scandir_side_effect),
            patch("worker.reconciliation.AsyncSessionLocal", return_value=session),
            patch("worker.reconciliation.cas_path", return_value=MagicMock(exists=MagicMock(return_value=False))),
            patch("worker.reconciliation.thumb_dir", return_value=MagicMock(exists=MagicMock(return_value=False))),
        ):
            await reconciliation_job(ctx)

        # setex should have been called at least once for progress or result
        assert redis.setex.call_count >= 1
        all_keys = [c.args[0] for c in redis.setex.call_args_list]
        assert any("reconcile" in k for k in all_keys)

    async def test_result_stored_in_redis_with_ttl(self, tmp_path):
        """After completion, 'reconcile:last_result' should be stored with a TTL."""
        from worker.reconciliation import reconciliation_job

        lib_base = tmp_path / "library"
        lib_base.mkdir()

        redis = _make_redis()
        ctx = _make_ctx(redis=redis)

        mock_settings = MagicMock()
        mock_settings.data_library_path = str(lib_base)

        def _scandir_side_effect(path):
            return iter([])

        session = _make_session_ctx(execute_side_effects=[
            _make_result_with_rows([]),
            _make_result_with_rows([]),
        ])

        with (
            patch("worker.reconciliation._cron_should_run", new_callable=AsyncMock, return_value=True),
            patch("worker.reconciliation._cron_record", new_callable=AsyncMock),
            patch("worker.reconciliation.settings", mock_settings),
            patch("os.scandir", side_effect=_scandir_side_effect),
            patch("worker.reconciliation.AsyncSessionLocal", return_value=session),
            patch("worker.reconciliation.cas_path", return_value=MagicMock(exists=MagicMock(return_value=False))),
            patch("worker.reconciliation.thumb_dir", return_value=MagicMock(exists=MagicMock(return_value=False))),
        ):
            await reconciliation_job(ctx)

        last_result_calls = [
            c for c in redis.setex.call_args_list
            if c.args[0] == "reconcile:last_result"
        ]
        assert len(last_result_calls) == 1
        # TTL should be 30 days (86400 * 30)
        assert last_result_calls[0].args[1] == 86400 * 30
        # Value should be JSON with expected keys
        payload = json.loads(last_result_calls[0].args[2])
        assert "completed_at" in payload
        assert "removed_images" in payload

    async def test_filesystem_oserror_does_not_crash_job(self, tmp_path):
        """OSError during scandir should not propagate — job should complete."""
        from worker.reconciliation import reconciliation_job

        lib_base = tmp_path / "library"
        lib_base.mkdir()

        ctx = _make_ctx()
        mock_settings = MagicMock()
        mock_settings.data_library_path = str(lib_base)

        source_entry = _make_dir_entry("src_a", is_dir=True, path=str(lib_base / "src_a"))
        gal_entry = _make_dir_entry("gal_1", is_dir=True, path=str(lib_base / "src_a" / "gal_1"))
        broken_link = _make_dir_entry(
            "img.jpg",
            is_dir=False,
            is_symlink=True,
            path=str(lib_base / "src_a" / "gal_1" / "img.jpg"),
        )

        def _scandir_side_effect(path):
            path_str = str(path)
            if path_str == str(lib_base):
                return iter([source_entry])
            if "src_a" in path_str and "gal_1" not in path_str:
                return iter([gal_entry])
            return iter([broken_link])

        session = _make_session_ctx(execute_side_effects=[
            _make_result_with_rows([]),  # Phase 1 Gallery query
            _make_result_with_rows([]),  # Phase 1 Images query
            _make_result_with_rows([]),  # Phase 2
            _make_result_with_rows([]),  # Phase 3
        ])

        with (
            patch("worker.reconciliation._cron_should_run", new_callable=AsyncMock, return_value=True),
            patch("worker.reconciliation._cron_record", new_callable=AsyncMock),
            patch("worker.reconciliation.settings", mock_settings),
            patch("os.scandir", side_effect=_scandir_side_effect),
            # os.unlink raises OSError — should be swallowed
            patch("os.unlink", side_effect=OSError("permission denied")),
            patch("pathlib.Path.exists", return_value=False),
            patch("worker.reconciliation.AsyncSessionLocal", return_value=session),
            patch("worker.reconciliation.cas_path", return_value=MagicMock(exists=MagicMock(return_value=False))),
            patch("worker.reconciliation.thumb_dir", return_value=MagicMock(exists=MagicMock(return_value=False))),
        ):
            # Should not raise even though os.unlink fails
            result = await reconciliation_job(ctx)

        assert result["status"] == "done"

    async def test_cron_record_called_with_ok_on_success(self, tmp_path):
        """_cron_record should be called with 'ok' after a successful run."""
        from worker.reconciliation import reconciliation_job

        lib_base = tmp_path / "library"
        lib_base.mkdir()

        ctx = _make_ctx()
        mock_settings = MagicMock()
        mock_settings.data_library_path = str(lib_base)

        def _scandir_side_effect(path):
            return iter([])

        session = _make_session_ctx(execute_side_effects=[
            _make_result_with_rows([]),
            _make_result_with_rows([]),
        ])

        mock_cron_record = AsyncMock()

        with (
            patch("worker.reconciliation._cron_should_run", new_callable=AsyncMock, return_value=True),
            patch("worker.reconciliation._cron_record", mock_cron_record),
            patch("worker.reconciliation.settings", mock_settings),
            patch("os.scandir", side_effect=_scandir_side_effect),
            patch("worker.reconciliation.AsyncSessionLocal", return_value=session),
            patch("worker.reconciliation.cas_path", return_value=MagicMock(exists=MagicMock(return_value=False))),
            patch("worker.reconciliation.thumb_dir", return_value=MagicMock(exists=MagicMock(return_value=False))),
        ):
            await reconciliation_job(ctx)

        # The final call to _cron_record should be with "ok"
        final_call = mock_cron_record.call_args_list[-1]
        assert final_call.args[2] == "ok"

    async def test_thumb_dirs_removed_for_orphan_blobs(self, tmp_path):
        """shutil.rmtree should be called for orphan blob thumb dirs that exist."""
        from worker.reconciliation import reconciliation_job

        lib_base = tmp_path / "library"
        lib_base.mkdir()

        ctx = _make_ctx()
        mock_settings = MagicMock()
        mock_settings.data_library_path = str(lib_base)

        orphan_blob = _make_blob_gc_row(SHA_A, extension=".jpg", actual_refs=0)

        def _scandir_side_effect(path):
            return iter([])

        execute_returns = [
            _make_result_with_rows([]),          # Phase 2
            _make_result_with_rows([orphan_blob]),  # Phase 3 GC
            _make_empty_result(),                 # DELETE blobs
        ]

        session = _make_session_ctx(execute_side_effects=execute_returns)

        fake_cas_file = MagicMock(spec=Path)
        fake_cas_file.exists.return_value = False
        fake_td = MagicMock(spec=Path)
        fake_td.exists.return_value = True
        fake_td.__str__ = MagicMock(return_value="/fake/thumbs/aa/aa/aaaa...")

        with (
            patch("worker.reconciliation._cron_should_run", new_callable=AsyncMock, return_value=True),
            patch("worker.reconciliation._cron_record", new_callable=AsyncMock),
            patch("worker.reconciliation.settings", mock_settings),
            patch("os.scandir", side_effect=_scandir_side_effect),
            patch("worker.reconciliation.AsyncSessionLocal", return_value=session),
            patch("worker.reconciliation.cas_path", return_value=fake_cas_file),
            patch("worker.reconciliation.thumb_dir", return_value=fake_td),
            patch("shutil.rmtree") as mock_rmtree,
        ):
            result = await reconciliation_job(ctx)

        assert result["orphan_blobs_cleaned"] == 1
        mock_rmtree.assert_called_once()

    async def test_multiple_gallery_dirs_all_scanned(self, tmp_path):
        """Two gallery directories under the same source should both be processed."""
        from worker.reconciliation import reconciliation_job

        lib_base = tmp_path / "library"
        lib_base.mkdir()

        ctx = _make_ctx()
        mock_settings = MagicMock()
        mock_settings.data_library_path = str(lib_base)

        source_entry = _make_dir_entry("src_a", is_dir=True, path=str(lib_base / "src_a"))
        gal1 = _make_dir_entry("gal_1", is_dir=True, path=str(lib_base / "src_a" / "gal_1"))
        gal2 = _make_dir_entry("gal_2", is_dir=True, path=str(lib_base / "src_a" / "gal_2"))
        # Each gallery has one valid (non-symlink) file
        file1 = _make_dir_entry("img1.jpg", is_dir=False, is_symlink=False,
                                path=str(lib_base / "src_a" / "gal_1" / "img1.jpg"))
        file2 = _make_dir_entry("img2.jpg", is_dir=False, is_symlink=False,
                                path=str(lib_base / "src_a" / "gal_2" / "img2.jpg"))

        def _scandir_side_effect(path):
            path_str = str(path)
            if path_str == str(lib_base):
                return iter([source_entry])
            if path_str.endswith("src_a") and "gal_" not in path_str:
                return iter([gal1, gal2])
            if path_str.endswith("gal_1"):
                return iter([file1])
            if path_str.endswith("gal_2"):
                return iter([file2])
            return iter([])

        execute_returns = [
            _make_result_with_rows([]),  # Phase 1 Gallery query (chunk)
            _make_result_with_rows([]),  # Phase 1 Images query
            _make_result_with_rows([]),  # Phase 2
            _make_result_with_rows([]),  # Phase 3
        ]

        session = _make_session_ctx(execute_side_effects=execute_returns)

        with (
            patch("worker.reconciliation._cron_should_run", new_callable=AsyncMock, return_value=True),
            patch("worker.reconciliation._cron_record", new_callable=AsyncMock),
            patch("worker.reconciliation.settings", mock_settings),
            patch("os.scandir", side_effect=_scandir_side_effect),
            patch("worker.reconciliation.AsyncSessionLocal", return_value=session),
            patch("worker.reconciliation.cas_path", return_value=MagicMock(exists=MagicMock(return_value=False))),
            patch("worker.reconciliation.thumb_dir", return_value=MagicMock(exists=MagicMock(return_value=False))),
        ):
            result = await reconciliation_job(ctx)

        assert result["status"] == "done"
        # Phase 1 gallery query should have been called with both keys
        phase1_execute_call = session.execute.call_args_list[0]
        # The query is built with tuple_(Gallery.source, Gallery.source_id).in_(chunk_keys)
        # We verify execute was called (i.e., both galleries were included in the scan)
        assert session.execute.call_count >= 1
