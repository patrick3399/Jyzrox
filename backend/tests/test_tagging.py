"""
Unit tests for worker.tagging.tag_job.

Strategy:
- For tests that exercise the full tagging path (which uses pg_insert + ORM
  list binding incompatible with SQLite), we mock AsyncSessionLocal with a
  fully-mocked session that returns controlled Image/Blob objects.
- For simpler tests (disabled / unavailable), no DB session is needed.
- Mock `settings.tag_model_enabled` via patch on `worker.tagging.settings`.
- Mock `httpx.AsyncClient` to avoid real network calls.
- Mock `worker.tagging.resolve_blob_path` to control file-existence checks.
"""

from contextlib import asynccontextmanager, contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@contextmanager
def _patch_runtime_settings(enabled: bool = True):
    """Patch the Redis-backed runtime settings reads (AIT-005) so tag_job
    tests don't touch Redis; thresholds pass through their env defaults."""
    with (
        patch("worker.tagging.get_toggle", new_callable=AsyncMock, return_value=enabled),
        patch(
            "worker.tagging.get_float_setting",
            new_callable=AsyncMock,
            side_effect=lambda key, default: default,
        ),
    ):
        yield


def _mock_settings(tag_model_enabled: bool = True) -> MagicMock:
    s = MagicMock()
    s.tag_model_enabled = tag_model_enabled
    s.tagger_url = "http://localhost:8765"
    s.tagger_timeout = 30
    s.tag_general_threshold = 0.35
    s.tag_character_threshold = 0.85
    return s


def _mock_http_client(available: bool = True, tags: list | None = None):
    """Build an httpx.AsyncClient mock with pre-configured /health and /predict."""
    if tags is None:
        tags = [
            {"namespace": "general", "name": "solo", "confidence": 0.95},
            {"namespace": "character", "name": "char_a", "confidence": 0.88},
        ]

    health_resp = MagicMock()
    health_resp.status_code = 200 if available else 503
    health_resp.json = MagicMock(return_value={"model_loaded": available})

    predict_resp = MagicMock()
    predict_resp.status_code = 200
    predict_resp.json = MagicMock(return_value={"tags": tags})
    predict_resp.raise_for_status = MagicMock()

    client = AsyncMock()
    client.get = AsyncMock(return_value=health_resp)
    client.post = AsyncMock(return_value=predict_resp)
    return client


def _make_mock_blob(sha256: str = "aa" * 32, extension: str = ".jpg") -> MagicMock:
    blob = MagicMock()
    blob.sha256 = sha256
    blob.extension = extension
    return blob


def _make_mock_image(
    img_id: int,
    gallery_id: int,
    blob: MagicMock,
    tags_array: list | None = None,
) -> MagicMock:
    img = MagicMock()
    img.id = img_id
    img.gallery_id = gallery_id
    img.blob = blob
    img.tags_array = tags_array or []
    return img


def _make_mock_session(images: list) -> MagicMock:
    """Return a mock async session that yields `images` from a scalars().all() query."""
    session = AsyncMock()

    # execute() → scalars() → all() → images list
    scalars_mock = MagicMock()
    scalars_mock.all = MagicMock(return_value=images)
    execute_result = MagicMock()
    execute_result.scalars = MagicMock(return_value=scalars_mock)

    # scalar_one_or_none() for tag lookups
    execute_result.scalar_one_or_none = MagicMock(return_value=None)
    execute_result.all = MagicMock(return_value=[])

    session.execute = AsyncMock(return_value=execute_result)
    session.commit = AsyncMock()
    return session


def _make_session_factory_from_mock(mock_session: MagicMock):
    """Wrap a mock session so ``async with AsyncSessionLocal() as s:`` yields it."""

    @asynccontextmanager
    async def _cm():
        yield mock_session

    class _Factory:
        def __call__(self):
            return _cm()

    return _Factory()


# ---------------------------------------------------------------------------
# TestTaggingJob
# ---------------------------------------------------------------------------


class TestTaggingJob:
    """Tests for worker.tagging.tag_job."""

    async def test_tag_model_enabled_false_returns_skipped(self):
        """When ai tagging is disabled (env default, no Redis override), job must return status='skipped'."""
        from worker.tagging import tag_job

        mock_s = _mock_settings(tag_model_enabled=False)
        with patch("worker.tagging.settings", mock_s), _patch_runtime_settings(enabled=False):
            result = await tag_job({}, gallery_id=1)

        assert result["status"] == "skipped"
        assert "ai_tagging_enabled" in result["reason"]

    async def test_tagger_unavailable_raises_for_retry(self):
        """When tagger health check fails, job must raise RuntimeError so SAQ retries — edge case #211.

        Before the fix, the job returned {"status": "skipped", "reason": "tagger_unavailable"},
        silently dropping the gallery from the tagging queue on any transient outage.
        """
        import pytest

        from worker.tagging import tag_job

        mock_s = _mock_settings(tag_model_enabled=True)
        unavail_client = _mock_http_client(available=False)

        with (
            patch("worker.tagging.settings", mock_s),
            _patch_runtime_settings(),
            patch("worker.tagging.httpx.AsyncClient") as mock_cls,
        ):
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=unavail_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            with pytest.raises(RuntimeError, match="tagger unavailable"):
                await tag_job({}, gallery_id=1)

    async def test_successful_tagging_returns_tagged_count(self, tmp_path):
        """Successful tagging of all images must return tagged count equal to image count."""
        from worker.tagging import tag_job

        fake_image_path = tmp_path / "img.jpg"
        fake_image_path.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)

        blob = _make_mock_blob()
        img = _make_mock_image(img_id=1, gallery_id=1, blob=blob)

        mock_session = _make_mock_session(images=[img])
        fake_db = _make_session_factory_from_mock(mock_session)

        mock_s = _mock_settings(tag_model_enabled=True)
        avail_client = _mock_http_client(available=True)

        with (
            patch("worker.tagging.settings", mock_s),
            _patch_runtime_settings(),
            patch("worker.tagging.AsyncSessionLocal", fake_db),
            patch("worker.tagging.resolve_blob_path", return_value=fake_image_path),
            patch("worker.tagging.httpx.AsyncClient") as mock_cls,
        ):
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=avail_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await tag_job({}, gallery_id=1)

        assert result["status"] == "done"
        assert result["tagged"] >= 1

    async def test_non_image_blob_skipped(self, tmp_path):
        """Video blobs must be skipped — tagged count must be 0."""
        from worker.tagging import tag_job

        fake_video_path = tmp_path / "vid.mp4"
        fake_video_path.write_bytes(b"\x00\x00\x00\x18ftyp")

        blob = _make_mock_blob(extension=".mp4")
        img = _make_mock_image(img_id=2, gallery_id=2, blob=blob)

        mock_session = _make_mock_session(images=[img])
        fake_db = _make_session_factory_from_mock(mock_session)

        mock_s = _mock_settings(tag_model_enabled=True)
        avail_client = _mock_http_client(available=True)

        with (
            patch("worker.tagging.settings", mock_s),
            _patch_runtime_settings(),
            patch("worker.tagging.AsyncSessionLocal", fake_db),
            patch("worker.tagging.resolve_blob_path", return_value=fake_video_path),
            patch("worker.tagging.httpx.AsyncClient") as mock_cls,
        ):
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=avail_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await tag_job({}, gallery_id=2)

        assert result["status"] == "done"
        assert result["tagged"] == 0

    async def test_one_image_failure_does_not_stop_others(self, tmp_path):
        """When one image's predict call raises, others must still be processed."""
        from worker.tagging import tag_job

        fake_path = tmp_path / "img.jpg"
        fake_path.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)

        blob_fail = _make_mock_blob(sha256="ff" * 32)
        blob_ok = _make_mock_blob(sha256="00" * 32)
        img_fail = _make_mock_image(img_id=10, gallery_id=3, blob=blob_fail)
        img_ok = _make_mock_image(img_id=11, gallery_id=3, blob=blob_ok)

        mock_session = _make_mock_session(images=[img_fail, img_ok])
        fake_db = _make_session_factory_from_mock(mock_session)

        mock_s = _mock_settings(tag_model_enabled=True)

        health_resp = MagicMock()
        health_resp.status_code = 200
        health_resp.json = MagicMock(return_value={"model_loaded": True})

        call_count = 0

        async def _post_side(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("predict failure")
            resp = MagicMock()
            resp.status_code = 200
            resp.json = MagicMock(return_value={"tags": [{"namespace": "general", "name": "solo", "confidence": 0.9}]})
            resp.raise_for_status = MagicMock()
            return resp

        client = AsyncMock()
        client.get = AsyncMock(return_value=health_resp)
        client.post = AsyncMock(side_effect=_post_side)

        with (
            patch("worker.tagging.settings", mock_s),
            _patch_runtime_settings(),
            patch("worker.tagging.AsyncSessionLocal", fake_db),
            patch("worker.tagging.resolve_blob_path", return_value=fake_path),
            patch("worker.tagging.httpx.AsyncClient") as mock_cls,
        ):
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await tag_job({}, gallery_id=3)

        assert result["status"] == "done"
        # Second image succeeded, so at least 1 was tagged
        assert result["tagged"] >= 1

    async def test_tags_merged_with_existing_tags_array(self, tmp_path):
        """New tags from tagger must be merged into the image's existing tags_array."""
        from worker.tagging import tag_job

        fake_path = tmp_path / "img.jpg"
        fake_path.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)

        blob = _make_mock_blob()
        img = _make_mock_image(img_id=20, gallery_id=4, blob=blob, tags_array=["existing:tag"])

        mock_session = _make_mock_session(images=[img])
        fake_db = _make_session_factory_from_mock(mock_session)

        mock_s = _mock_settings(tag_model_enabled=True)
        avail_client = _mock_http_client(
            available=True,
            tags=[{"namespace": "general", "name": "new_tag", "confidence": 0.9}],
        )

        with (
            patch("worker.tagging.settings", mock_s),
            _patch_runtime_settings(),
            patch("worker.tagging.AsyncSessionLocal", fake_db),
            patch("worker.tagging.resolve_blob_path", return_value=fake_path),
            patch("worker.tagging.httpx.AsyncClient") as mock_cls,
        ):
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=avail_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await tag_job({}, gallery_id=4)

        assert result["status"] == "done"
        assert result["tagged"] >= 1
        # The image's tags_array must contain both old and new tags
        assert "general:new_tag" in img.tags_array
        assert "existing:tag" in img.tags_array

    async def test_empty_gallery_returns_zero_tagged(self):
        """Gallery with no images must return tagged=0."""
        from worker.tagging import tag_job

        mock_session = _make_mock_session(images=[])
        fake_db = _make_session_factory_from_mock(mock_session)

        mock_s = _mock_settings(tag_model_enabled=True)
        avail_client = _mock_http_client(available=True)

        with (
            patch("worker.tagging.settings", mock_s),
            _patch_runtime_settings(),
            patch("worker.tagging.AsyncSessionLocal", fake_db),
            patch("worker.tagging.httpx.AsyncClient") as mock_cls,
        ):
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=avail_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await tag_job({}, gallery_id=99)

        assert result["status"] == "done"
        assert result["tagged"] == 0

    async def test_missing_blob_file_skipped(self, tmp_path):
        """Image whose blob file does not exist on disk must be silently skipped."""
        from worker.tagging import tag_job

        missing_path = tmp_path / "nonexistent.jpg"
        # Intentionally not created — path does not exist

        blob = _make_mock_blob()
        img = _make_mock_image(img_id=30, gallery_id=5, blob=blob)

        mock_session = _make_mock_session(images=[img])
        fake_db = _make_session_factory_from_mock(mock_session)

        mock_s = _mock_settings(tag_model_enabled=True)
        avail_client = _mock_http_client(available=True)

        with (
            patch("worker.tagging.settings", mock_s),
            _patch_runtime_settings(),
            patch("worker.tagging.AsyncSessionLocal", fake_db),
            patch("worker.tagging.resolve_blob_path", return_value=missing_path),
            patch("worker.tagging.httpx.AsyncClient") as mock_cls,
        ):
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=avail_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await tag_job({}, gallery_id=5)

        assert result["status"] == "done"
        assert result["tagged"] == 0


# ---------------------------------------------------------------------------
# Regression: AIT-005 — Redis runtime settings must actually drive tag_job
# ---------------------------------------------------------------------------


class TestAiTaggingRuntimeSettings:
    """setting:ai_tagging_enabled and the thresholds are runtime (Redis)
    settings; before the fix tag_job only read env vars, so the admin UI
    toggle was dead — AIT-005."""

    async def test_redis_toggle_off_skips_tag_job_even_when_env_enabled(self):
        """Turning the UI toggle off must stop tag_job even if TAG_MODEL_ENABLED=true."""
        from worker.tagging import tag_job

        mock_s = _mock_settings(tag_model_enabled=True)
        with (
            patch("worker.tagging.settings", mock_s),
            patch("worker.tagging.get_toggle", new_callable=AsyncMock, return_value=False) as mock_toggle,
        ):
            result = await tag_job({}, gallery_id=1)

        assert result["status"] == "skipped"
        assert "ai_tagging_enabled" in result["reason"]
        mock_toggle.assert_awaited_once_with("setting:ai_tagging_enabled", True)

    async def test_redis_toggle_on_runs_tag_job_even_when_env_disabled(self, tmp_path):
        """Turning the UI toggle on must run tag_job even if TAG_MODEL_ENABLED=false."""
        from worker.tagging import tag_job

        fake_path = tmp_path / "img.jpg"
        fake_path.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)

        blob = _make_mock_blob()
        img = _make_mock_image(img_id=1, gallery_id=1, blob=blob)
        fake_db = _make_session_factory_from_mock(_make_mock_session(images=[img]))

        mock_s = _mock_settings(tag_model_enabled=False)
        avail_client = _mock_http_client(available=True)

        with (
            patch("worker.tagging.settings", mock_s),
            patch("worker.tagging.get_toggle", new_callable=AsyncMock, return_value=True),
            patch("worker.tagging.get_float_setting", new_callable=AsyncMock, side_effect=lambda key, default: default),
            patch("worker.tagging.AsyncSessionLocal", fake_db),
            patch("worker.tagging.resolve_blob_path", return_value=fake_path),
            patch("worker.tagging.httpx.AsyncClient") as mock_cls,
        ):
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=avail_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await tag_job({}, gallery_id=1)

        assert result["status"] == "done"
        assert result["tagged"] >= 1

    async def test_tag_job_uses_runtime_thresholds_from_redis(self, tmp_path):
        """Thresholds must come from the Redis runtime settings, not env-only
        config, so admins can tune them without restarting the worker."""
        from worker.tagging import tag_job

        fake_path = tmp_path / "img.jpg"
        fake_path.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)

        blob = _make_mock_blob()
        img = _make_mock_image(img_id=1, gallery_id=1, blob=blob)
        fake_db = _make_session_factory_from_mock(_make_mock_session(images=[img]))

        mock_s = _mock_settings(tag_model_enabled=True)
        avail_client = _mock_http_client(available=True)

        runtime_thresholds = {
            "setting:tag_general_threshold": 0.7,
            "setting:tag_character_threshold": 0.9,
        }

        with (
            patch("worker.tagging.settings", mock_s),
            patch("worker.tagging.get_toggle", new_callable=AsyncMock, return_value=True),
            patch(
                "worker.tagging.get_float_setting",
                new_callable=AsyncMock,
                side_effect=lambda key, default: runtime_thresholds.get(key, default),
            ),
            patch("worker.tagging.AsyncSessionLocal", fake_db),
            patch("worker.tagging.resolve_blob_path", return_value=fake_path),
            patch("worker.tagging.httpx.AsyncClient") as mock_cls,
        ):
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=avail_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await tag_job({}, gallery_id=1)

        assert result["status"] == "done"
        predict_payload = avail_client.post.await_args.kwargs["json"]
        assert predict_payload["general_threshold"] == 0.7
        assert predict_payload["character_threshold"] == 0.9


# ---------------------------------------------------------------------------
# Regression: edge case #211 — tagger transient outage must raise, not skip
# ---------------------------------------------------------------------------


class TestTaggerUnavailableRaisesForRetry:
    """tag_job must raise RuntimeError on transient outage so SAQ retries — edge case #211."""

    async def test_enabled_false_still_returns_skipped(self):
        """ai tagging disabled is a permanent skip, not a transient error."""
        from worker.tagging import tag_job

        mock_s = _mock_settings(tag_model_enabled=False)
        with patch("worker.tagging.settings", mock_s), _patch_runtime_settings(enabled=False):
            result = await tag_job({}, gallery_id=99)

        assert result["status"] == "skipped"
