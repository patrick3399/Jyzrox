"""
Tests for worker/helpers.py shared helper functions.

Covers:
- _set_job_status: status transitions, finished_at logic, error clearing,
  job-not-found, None job_id early return, publish exception swallowed,
  DB exception caught.
- _set_job_progress: progress update, job-not-found, None job_id early
  return, publish exception swallowed, DB exception caught.
- _cron_should_run: disabled via explicit b"0", disabled via default,
  no last_run (first run), next_run in future, next_run in past, custom
  cron_expr from Redis.
- _cron_record: sets last_run + last_status, sets error key, deletes error
  key when no error.
- _validate_image_magic: AVIF and HEIC ftyp-box detection (not duplicating
  tests already in TestImageValidation in test_retry.py).
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_session(job=None):
    """Return a mock AsyncSessionLocal context manager."""
    session = AsyncMock()
    session.get = AsyncMock(return_value=job)
    session.commit = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


def _make_job(status="running", error=None, finished_at=None, progress=None, user_id=1):
    """Create a minimal mock DownloadJob."""
    job = MagicMock()
    job.id = uuid.uuid4()
    job.status = status
    job.error = error
    job.finished_at = finished_at
    job.progress = progress or {}
    job.user_id = user_id
    return job


def _make_mock_redis_for_cron(
    enabled=None,
    cron_expr=None,
    last_run=None,
):
    """Build an AsyncMock Redis whose .get() returns bytes or None for cron keys."""
    mock_redis = AsyncMock()

    async def _get(key):
        if key.endswith(":enabled"):
            return enabled
        if key.endswith(":cron_expr"):
            return cron_expr
        if key.endswith(":last_run"):
            return last_run
        return None

    mock_redis.get = AsyncMock(side_effect=_get)
    return mock_redis


# ---------------------------------------------------------------------------
# _set_job_status
# ---------------------------------------------------------------------------


class TestSetJobStatus:
    """Unit tests for _set_job_status."""

    async def test_none_job_id_returns_early(self):
        """job_id=None should return immediately without touching the DB."""
        from worker.helpers import _set_job_status

        mock_session = _make_mock_session()
        with patch("worker.helpers.AsyncSessionLocal", return_value=mock_session):
            await _set_job_status(None, "running")

        mock_session.__aenter__.assert_not_called()

    async def test_running_status_clears_error(self):
        """Status 'running' with no error arg should clear a stale error."""
        from worker.helpers import _set_job_status

        job = _make_job(status="failed", error="previous error")
        mock_session = _make_mock_session(job)

        with (
            patch("worker.helpers.AsyncSessionLocal", return_value=mock_session),
            patch("worker.helpers.publish_job_event", new_callable=AsyncMock),
        ):
            await _set_job_status(str(job.id), "running")

        assert job.status == "running"
        assert job.error is None

    async def test_running_status_does_not_set_finished_at(self):
        """Status 'running' should NOT set finished_at."""
        from worker.helpers import _set_job_status

        job = _make_job(finished_at=None)
        mock_session = _make_mock_session(job)

        with (
            patch("worker.helpers.AsyncSessionLocal", return_value=mock_session),
            patch("worker.helpers.publish_job_event", new_callable=AsyncMock),
        ):
            await _set_job_status(str(job.id), "running")

        assert job.finished_at is None

    async def test_paused_status_does_not_set_finished_at(self):
        """Status 'paused' should NOT set finished_at (intermediate state)."""
        from worker.helpers import _set_job_status

        job = _make_job(finished_at=None)
        mock_session = _make_mock_session(job)

        with (
            patch("worker.helpers.AsyncSessionLocal", return_value=mock_session),
            patch("worker.helpers.publish_job_event", new_callable=AsyncMock),
        ):
            await _set_job_status(str(job.id), "paused")

        assert job.finished_at is None

    @pytest.mark.parametrize("terminal_status", ["done", "failed", "cancelled", "partial"])
    async def test_terminal_status_sets_finished_at(self, terminal_status):
        """Terminal statuses should set finished_at to now."""
        from worker.helpers import _set_job_status

        job = _make_job(finished_at=None)
        mock_session = _make_mock_session(job)
        before = datetime.now(UTC)

        with (
            patch("worker.helpers.AsyncSessionLocal", return_value=mock_session),
            patch("worker.helpers.publish_job_event", new_callable=AsyncMock),
        ):
            await _set_job_status(str(job.id), terminal_status)

        assert job.finished_at is not None
        assert job.finished_at >= before

    async def test_error_arg_is_stored(self):
        """Passing an error string should set job.error."""
        from worker.helpers import _set_job_status

        job = _make_job()
        mock_session = _make_mock_session(job)

        with (
            patch("worker.helpers.AsyncSessionLocal", return_value=mock_session),
            patch("worker.helpers.publish_job_event", new_callable=AsyncMock),
        ):
            await _set_job_status(str(job.id), "failed", error="timeout")

        assert job.error == "timeout"
        assert job.status == "failed"

    async def test_job_not_found_does_not_raise(self):
        """If the job does not exist in DB, the function should return silently."""
        from worker.helpers import _set_job_status

        mock_session = _make_mock_session(job=None)

        with patch("worker.helpers.AsyncSessionLocal", return_value=mock_session):
            # Should not raise
            await _set_job_status(str(uuid.uuid4()), "done")

        mock_session.commit.assert_not_called()

    async def test_publish_exception_is_swallowed(self):
        """Exception from publish_job_event should not propagate."""
        from worker.helpers import _set_job_status

        job = _make_job()
        mock_session = _make_mock_session(job)

        with (
            patch("worker.helpers.AsyncSessionLocal", return_value=mock_session),
            patch(
                "worker.helpers.publish_job_event",
                new_callable=AsyncMock,
                side_effect=Exception("Redis down"),
            ),
        ):
            # Should complete without raising
            await _set_job_status(str(job.id), "done")

        assert job.status == "done"

    async def test_db_exception_is_caught(self):
        """SQLAlchemyError during session should be caught, not raised."""
        import sqlalchemy.exc
        from worker.helpers import _set_job_status

        bad_session = AsyncMock()
        bad_session.__aenter__ = AsyncMock(
            side_effect=sqlalchemy.exc.OperationalError("stmt", {}, Exception("db down"))
        )
        bad_session.__aexit__ = AsyncMock(return_value=False)

        with patch("worker.helpers.AsyncSessionLocal", return_value=bad_session):
            # Should not raise
            await _set_job_status(str(uuid.uuid4()), "done")

    async def test_commit_is_called_after_update(self):
        """session.commit() must be called after setting job fields."""
        from worker.helpers import _set_job_status

        job = _make_job()
        mock_session = _make_mock_session(job)

        with (
            patch("worker.helpers.AsyncSessionLocal", return_value=mock_session),
            patch("worker.helpers.publish_job_event", new_callable=AsyncMock),
        ):
            await _set_job_status(str(job.id), "done")

        mock_session.commit.assert_called_once()


# ---------------------------------------------------------------------------
# _set_job_progress
# ---------------------------------------------------------------------------


class TestSetJobProgress:
    """Unit tests for _set_job_progress."""

    async def test_none_job_id_returns_early(self):
        """job_id=None should return immediately without touching the DB."""
        from worker.helpers import _set_job_progress

        mock_session = _make_mock_session()
        with patch("worker.helpers.AsyncSessionLocal", return_value=mock_session):
            await _set_job_progress(None, {"total": 10})

        mock_session.__aenter__.assert_not_called()

    async def test_progress_is_updated(self):
        """Job progress JSONB should be replaced with the supplied dict."""
        from worker.helpers import _set_job_progress

        job = _make_job(progress={"done": 0, "total": 5})
        mock_session = _make_mock_session(job)
        new_progress = {"done": 3, "total": 5}

        with (
            patch("worker.helpers.AsyncSessionLocal", return_value=mock_session),
            patch("worker.helpers.publish_job_event", new_callable=AsyncMock),
        ):
            await _set_job_progress(str(job.id), new_progress)

        assert job.progress == new_progress
        mock_session.commit.assert_called_once()

    async def test_job_not_found_does_not_commit(self):
        """If the job row is missing, commit should not be called."""
        from worker.helpers import _set_job_progress

        mock_session = _make_mock_session(job=None)
        with patch("worker.helpers.AsyncSessionLocal", return_value=mock_session):
            await _set_job_progress(str(uuid.uuid4()), {"x": 1})

        mock_session.commit.assert_not_called()

    async def test_publish_exception_is_swallowed(self):
        """Exception from publish_job_event inside progress update should not propagate."""
        from worker.helpers import _set_job_progress

        job = _make_job()
        mock_session = _make_mock_session(job)

        with (
            patch("worker.helpers.AsyncSessionLocal", return_value=mock_session),
            patch(
                "worker.helpers.publish_job_event",
                new_callable=AsyncMock,
                side_effect=RuntimeError("publish failed"),
            ),
        ):
            await _set_job_progress(str(job.id), {"done": 1})

        assert job.progress == {"done": 1}

    async def test_db_exception_is_caught(self):
        """SQLAlchemyError during session should be caught, not raised."""
        import sqlalchemy.exc
        from worker.helpers import _set_job_progress

        bad_session = AsyncMock()
        bad_session.__aenter__ = AsyncMock(
            side_effect=sqlalchemy.exc.OperationalError("stmt", {}, Exception("db error"))
        )
        bad_session.__aexit__ = AsyncMock(return_value=False)

        with patch("worker.helpers.AsyncSessionLocal", return_value=bad_session):
            await _set_job_progress(str(uuid.uuid4()), {"x": 1})


# ---------------------------------------------------------------------------
# _cron_should_run
# ---------------------------------------------------------------------------


class TestCronShouldRun:
    """Unit tests for _cron_should_run."""

    async def test_disabled_explicit_zero_returns_false(self):
        """enabled=b'0' in Redis should always return False regardless of defaults."""
        from worker.helpers import _cron_should_run

        mock_redis = _make_mock_redis_for_cron(enabled=b"0")
        ctx = {"redis": mock_redis}

        result = await _cron_should_run(ctx, "my_task", "* * * * *", default_enabled=True)

        assert result is False

    async def test_disabled_via_default_enabled_false(self):
        """enabled=None + default_enabled=False should return False."""
        from worker.helpers import _cron_should_run

        mock_redis = _make_mock_redis_for_cron(enabled=None)
        ctx = {"redis": mock_redis}

        result = await _cron_should_run(ctx, "my_task", "* * * * *", default_enabled=False)

        assert result is False

    async def test_enabled_none_default_true_proceeds(self):
        """enabled=None + default_enabled=True should NOT short-circuit (proceeds to time check)."""
        from worker.helpers import _cron_should_run

        # No last_run → first run → True
        mock_redis = _make_mock_redis_for_cron(enabled=None, last_run=None)
        ctx = {"redis": mock_redis}

        result = await _cron_should_run(ctx, "my_task", "* * * * *", default_enabled=True)

        assert result is True

    async def test_no_last_run_returns_true(self):
        """No last_run key in Redis means first run — should always return True."""
        from worker.helpers import _cron_should_run

        mock_redis = _make_mock_redis_for_cron(enabled=b"1", last_run=None)
        ctx = {"redis": mock_redis}

        result = await _cron_should_run(ctx, "my_task", "0 */6 * * *")

        assert result is True

    async def test_next_run_in_future_returns_false(self):
        """If the next scheduled run is in the future, should return False."""
        from worker.helpers import _cron_should_run

        # Use a cron that runs once per day; set last_run to just now so
        # next_run is ~24 h away.
        last_run = datetime.now(UTC).isoformat().encode()
        mock_redis = _make_mock_redis_for_cron(enabled=b"1", last_run=last_run)
        ctx = {"redis": mock_redis}

        result = await _cron_should_run(ctx, "my_task", "0 3 * * *")

        assert result is False

    async def test_next_run_in_past_returns_true(self):
        """If next_run is in the past, the job is overdue and should return True."""
        from worker.helpers import _cron_should_run

        # last_run was 2 days ago; a daily cron's next_run was 1 day ago.
        last_run = (datetime.now(UTC) - timedelta(days=2)).isoformat().encode()
        mock_redis = _make_mock_redis_for_cron(enabled=b"1", last_run=last_run)
        ctx = {"redis": mock_redis}

        result = await _cron_should_run(ctx, "my_task", "0 3 * * *")

        assert result is True

    async def test_custom_cron_expr_from_redis(self):
        """A custom cron_expr stored in Redis should override the default."""
        from worker.helpers import _cron_should_run

        # Custom expr: every minute. last_run 2 minutes ago → overdue → True.
        last_run = (datetime.now(UTC) - timedelta(minutes=2)).isoformat().encode()

        mock_redis = AsyncMock()

        async def _get(key):
            if key.endswith(":enabled"):
                return b"1"
            if key.endswith(":cron_expr"):
                return b"* * * * *"  # every minute
            if key.endswith(":last_run"):
                return last_run
            return None

        mock_redis.get = AsyncMock(side_effect=_get)
        ctx = {"redis": mock_redis}

        # Default cron would be something unlikely to be due, but custom overrides it.
        result = await _cron_should_run(ctx, "my_task", "0 0 1 1 *")

        assert result is True

    async def test_enabled_byte_one_not_disabled(self):
        """enabled=b'1' should not trigger early-return; proceeds to time check."""
        from worker.helpers import _cron_should_run

        # No last_run → first run → True
        mock_redis = _make_mock_redis_for_cron(enabled=b"1", last_run=None)
        ctx = {"redis": mock_redis}

        result = await _cron_should_run(ctx, "task_x", "*/5 * * * *")

        assert result is True


# ---------------------------------------------------------------------------
# _cron_record
# ---------------------------------------------------------------------------


class TestCronRecord:
    """Unit tests for _cron_record."""

    def _make_pipeline_mock(self):
        """Return a MagicMock pipeline with async execute."""
        pipe = MagicMock()
        pipe.set = MagicMock()
        pipe.delete = MagicMock()
        pipe.execute = AsyncMock(return_value=None)
        return pipe

    async def test_records_last_run_and_status(self):
        """Should call pipe.set for last_run and last_status keys."""
        from worker.helpers import _cron_record

        pipe = self._make_pipeline_mock()
        mock_redis = MagicMock()
        mock_redis.pipeline = MagicMock(return_value=pipe)
        ctx = {"redis": mock_redis}

        await _cron_record(ctx, "my_task", "ok")

        set_calls = {args[0]: args[1] for args in (c.args for c in pipe.set.call_args_list)}
        assert "cron:my_task:last_run" in set_calls, "last_run key was not set"
        assert "cron:my_task:last_status" in set_calls, "last_status key was not set"
        assert set_calls["cron:my_task:last_status"] == "ok"

    async def test_records_last_run_timestamp_format(self):
        """last_run value stored should be a valid ISO-format datetime string."""
        from worker.helpers import _cron_record

        pipe = self._make_pipeline_mock()
        mock_redis = MagicMock()
        mock_redis.pipeline = MagicMock(return_value=pipe)
        ctx = {"redis": mock_redis}

        before = datetime.now(UTC)
        await _cron_record(ctx, "my_task", "ok")

        set_calls = {args[0]: args[1] for args in (c.args for c in pipe.set.call_args_list)}
        raw_ts = set_calls["cron:my_task:last_run"]
        ts = datetime.fromisoformat(raw_ts)
        assert ts >= before

    async def test_with_error_sets_error_key(self):
        """When error is provided, pipe.set should be called for last_error key."""
        from worker.helpers import _cron_record

        pipe = self._make_pipeline_mock()
        mock_redis = MagicMock()
        mock_redis.pipeline = MagicMock(return_value=pipe)
        ctx = {"redis": mock_redis}

        await _cron_record(ctx, "my_task", "failed", error="something went wrong")

        set_calls = {args[0]: args[1] for args in (c.args for c in pipe.set.call_args_list)}
        assert "cron:my_task:last_error" in set_calls
        assert set_calls["cron:my_task:last_error"] == "something went wrong"
        pipe.delete.assert_not_called()

    async def test_without_error_deletes_error_key(self):
        """When error is None, pipe.delete should be called for last_error key."""
        from worker.helpers import _cron_record

        pipe = self._make_pipeline_mock()
        mock_redis = MagicMock()
        mock_redis.pipeline = MagicMock(return_value=pipe)
        ctx = {"redis": mock_redis}

        await _cron_record(ctx, "my_task", "ok", error=None)

        pipe.delete.assert_called_once_with("cron:my_task:last_error")
        set_calls = [args[0] for args in (c.args for c in pipe.set.call_args_list)]
        assert "cron:my_task:last_error" not in set_calls

    async def test_execute_is_awaited(self):
        """pipe.execute() must be awaited (proves pipeline is flushed)."""
        from worker.helpers import _cron_record

        pipe = self._make_pipeline_mock()
        mock_redis = MagicMock()
        mock_redis.pipeline = MagicMock(return_value=pipe)
        ctx = {"redis": mock_redis}

        await _cron_record(ctx, "my_task", "ok")

        pipe.execute.assert_called_once()

    async def test_task_id_used_in_key_namespace(self):
        """Keys must be namespaced with the supplied task_id."""
        from worker.helpers import _cron_record

        pipe = self._make_pipeline_mock()
        mock_redis = MagicMock()
        mock_redis.pipeline = MagicMock(return_value=pipe)
        ctx = {"redis": mock_redis}

        await _cron_record(ctx, "special_task_42", "ok")

        set_keys = [c.args[0] for c in pipe.set.call_args_list]
        assert all("special_task_42" in k for k in set_keys)


# ---------------------------------------------------------------------------
# _validate_image_magic — AVIF / HEIC only
# (JPEG, PNG, GIF, WebP, truncated, corrupt, nonexistent covered in test_retry.py)
# ---------------------------------------------------------------------------


class TestValidateImageMagicFtypBox:
    """Tests for the AVIF/HEIC ftyp-box special case in _validate_image_magic."""

    def _write_ftyp_file(self, tmp_path, filename):
        """Write a minimal file with 'ftyp' at bytes 4-7."""
        # Structure: 4 bytes size + b'ftyp' + 4 bytes brand = 12 bytes
        data = b'\x00\x00\x00\x1c' + b'ftyp' + b'avif' + b'\x00' * 4
        f = tmp_path / filename
        f.write_bytes(data)
        return f

    def test_avif_ftyp_valid(self, tmp_path):
        """File with ftyp box and .avif extension should return True."""
        from worker.helpers import _validate_image_magic

        f = self._write_ftyp_file(tmp_path, "image.avif")
        assert _validate_image_magic(f) is True

    def test_heic_ftyp_valid(self, tmp_path):
        """File with ftyp box and .heic extension should return True."""
        from worker.helpers import _validate_image_magic

        f = self._write_ftyp_file(tmp_path, "photo.heic")
        assert _validate_image_magic(f) is True

    def test_ftyp_box_wrong_extension_returns_false(self, tmp_path):
        """ftyp box with a non-AVIF/HEIC extension should return False."""
        from worker.helpers import _validate_image_magic

        f = self._write_ftyp_file(tmp_path, "image.jpg")
        assert _validate_image_magic(f) is False

    def test_ftyp_box_png_extension_returns_false(self, tmp_path):
        """ftyp box with .png extension should be rejected."""
        from worker.helpers import _validate_image_magic

        f = self._write_ftyp_file(tmp_path, "image.png")
        assert _validate_image_magic(f) is False

    def test_avif_uppercase_extension(self, tmp_path):
        """Extension check is case-insensitive (.AVIF should work)."""
        from worker.helpers import _validate_image_magic

        f = self._write_ftyp_file(tmp_path, "image.AVIF")
        assert _validate_image_magic(f) is True

    def test_heic_uppercase_extension(self, tmp_path):
        """Extension check is case-insensitive (.HEIC should work)."""
        from worker.helpers import _validate_image_magic

        f = self._write_ftyp_file(tmp_path, "photo.HEIC")
        assert _validate_image_magic(f) is True

    def test_ftyp_at_wrong_offset_returns_false(self, tmp_path):
        """'ftyp' at offset 0 (not offset 4) should not match the ftyp rule."""
        from worker.helpers import _validate_image_magic

        # Put 'ftyp' at the very start — this is NOT the ISOBMFF ftyp box pattern
        data = b'ftyp' + b'\x00' * 8
        f = tmp_path / "image.avif"
        f.write_bytes(data)
        # 'ftyp' at offset 0 is not a known magic prefix → should fail
        assert _validate_image_magic(f) is False

    def test_short_file_before_ftyp_offset_returns_false(self, tmp_path):
        """File that is exactly 7 bytes (< 8 needed for ftyp check) returns False."""
        from worker.helpers import _validate_image_magic

        # 7 bytes: len check `len(header) >= 8` will be False
        data = b'\x00\x00\x00\x1c' + b'fty'  # only 7 bytes
        f = tmp_path / "image.avif"
        f.write_bytes(data)
        assert _validate_image_magic(f) is False


# ---------------------------------------------------------------------------
# rebuild_tag_counts
# ---------------------------------------------------------------------------


class TestRebuildTagCounts:
    """worker.tag_helpers.rebuild_tag_counts recalculates tag counts from gallery_tags."""

    async def _insert_tag(self, session, namespace, name, count=0):
        """Insert a tag and return its id."""
        from sqlalchemy import text as _text
        await session.execute(
            _text(
                "INSERT OR IGNORE INTO tags (namespace, name, count) "
                "VALUES (:ns, :name, :count)"
            ),
            {"ns": namespace, "name": name, "count": count},
        )
        await session.commit()
        result = await session.execute(
            _text("SELECT id FROM tags WHERE namespace = :ns AND name = :name"),
            {"ns": namespace, "name": name},
        )
        return result.scalar()

    async def _insert_gallery(self, session, source_id="g1"):
        """Insert a gallery and return its id."""
        from sqlalchemy import text as _text
        await session.execute(
            _text(
                "INSERT OR IGNORE INTO galleries (source, source_id, title) "
                "VALUES ('test', :sid, 'Test')"
            ),
            {"sid": source_id},
        )
        await session.commit()
        result = await session.execute(
            _text("SELECT id FROM galleries WHERE source_id = :sid"),
            {"sid": source_id},
        )
        return result.scalar()

    async def _insert_gallery_tag(self, session, gallery_id, tag_id):
        """Insert a gallery_tag row."""
        from sqlalchemy import text as _text
        await session.execute(
            _text(
                "INSERT OR IGNORE INTO gallery_tags (gallery_id, tag_id, confidence, source) "
                "VALUES (:gid, :tid, 1.0, 'metadata')"
            ),
            {"gid": gallery_id, "tid": tag_id},
        )
        await session.commit()

    async def _get_tag_count(self, session, tag_id):
        """Get the current count for a tag."""
        from sqlalchemy import text as _text
        result = await session.execute(
            _text("SELECT count FROM tags WHERE id = :tid"),
            {"tid": tag_id},
        )
        return result.scalar()

    async def test_rebuild_corrects_drifted_counts(self, db_session):
        """Tags with incorrect counts are corrected to match actual gallery_tags."""
        from worker.tag_helpers import rebuild_tag_counts

        # Create a tag with count=99 (wrong)
        tag_id = await self._insert_tag(db_session, "general", "rebuild_drift", count=99)
        gal_id = await self._insert_gallery(db_session, source_id="rebuild_g1")

        # Link tag to 1 gallery
        await self._insert_gallery_tag(db_session, gal_id, tag_id)

        # Rebuild — should correct count to 1
        await rebuild_tag_counts(db_session)
        await db_session.commit()

        actual = await self._get_tag_count(db_session, tag_id)
        assert actual == 1

    async def test_rebuild_zeros_orphan_tags(self, db_session):
        """Tags with no gallery_tags entries get count=0."""
        from worker.tag_helpers import rebuild_tag_counts

        # Create a tag with count=5 but no gallery_tags
        tag_id = await self._insert_tag(db_session, "general", "rebuild_orphan", count=5)

        await rebuild_tag_counts(db_session)
        await db_session.commit()

        actual = await self._get_tag_count(db_session, tag_id)
        assert actual == 0

    async def test_rebuild_handles_multiple_galleries(self, db_session):
        """A tag linked to 3 galleries should have count=3."""
        from worker.tag_helpers import rebuild_tag_counts

        tag_id = await self._insert_tag(db_session, "general", "rebuild_multi", count=0)
        for i in range(3):
            gal_id = await self._insert_gallery(db_session, source_id=f"rebuild_multi_g{i}")
            await self._insert_gallery_tag(db_session, gal_id, tag_id)

        await rebuild_tag_counts(db_session)
        await db_session.commit()

        actual = await self._get_tag_count(db_session, tag_id)
        assert actual == 3

    async def test_rebuild_returns_rowcount(self, db_session):
        """rebuild_tag_counts should return the number of tags updated."""
        from worker.tag_helpers import rebuild_tag_counts

        tag_id = await self._insert_tag(db_session, "general", "rebuild_rc", count=99)
        gal_id = await self._insert_gallery(db_session, source_id="rebuild_rc_g")
        await self._insert_gallery_tag(db_session, gal_id, tag_id)

        result = await rebuild_tag_counts(db_session)
        await db_session.commit()
        # At least 1 tag was updated
        assert result >= 1
