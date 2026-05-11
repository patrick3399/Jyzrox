"""
Integration tests for the saucenao router (/api/saucenao/search).

Mocks:
- routers.saucenao.get_credential   — controls API key availability
- routers.saucenao.async_session    — controls DB row lookup
- routers.saucenao.resolve_blob_path — controls file existence/size
- routers.saucenao.search_by_image  — controls SauceNAO response/errors
- PIL.Image.open                    — controls the resize path

Covers previously uncovered lines: 32-78.
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from services.saucenao import RateLimitError, SauceNaoError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_blob(sha256: str = "abc123", extension: str = ".jpg") -> MagicMock:
    """Build a minimal Blob-like mock."""
    blob = MagicMock()
    blob.sha256 = sha256
    blob.extension = extension
    return blob


def _make_mock_session(blob=None):
    """
    Build a mock async_session context manager.

    The router calls:
        async with async_session() as session:
            result = await session.execute(...)
            row = result.one_or_none()
            _, blob = row.tuple()
    """
    session = AsyncMock()

    if blob is None:
        # one_or_none returns None → 404 path
        result_mock = MagicMock()
        result_mock.one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result_mock)
    else:
        row_mock = MagicMock()
        # row.tuple() returns (image, blob)
        image_mock = MagicMock()
        row_mock.tuple.return_value = (image_mock, blob)
        result_mock = MagicMock()
        result_mock.one_or_none.return_value = row_mock
        session.execute = AsyncMock(return_value=result_mock)

    @asynccontextmanager
    async def _ctx():
        yield session

    class _Factory:
        def __call__(self):
            return _ctx()

    return _Factory()


def _make_path_mock(exists: bool = True, size: int = 1024) -> MagicMock:
    """Build a mock Path object."""
    path = MagicMock()
    path.exists.return_value = exists
    stat_result = MagicMock()
    stat_result.st_size = size
    path.stat.return_value = stat_result
    path.read_bytes.return_value = b"fake-image-data"
    return path


# ---------------------------------------------------------------------------
# POST /api/saucenao/search
# ---------------------------------------------------------------------------


async def test_saucenao_search_no_api_key_returns_400(client):
    """When get_credential returns None, endpoint must return 400."""
    with patch("routers.saucenao.get_credential", AsyncMock(return_value=None)):
        resp = await client.post("/api/saucenao/search", json={"image_id": 1})

    assert resp.status_code == 400
    assert resp.json()["detail"] == "saucenao_not_configured"


async def test_saucenao_search_image_not_found_returns_404(client):
    """When the DB row is not found, endpoint must return 404."""
    mock_session = _make_mock_session(blob=None)

    with (
        patch("routers.saucenao.get_credential", AsyncMock(return_value="api-key")),
        patch("routers.saucenao.async_session", mock_session),
    ):
        resp = await client.post("/api/saucenao/search", json={"image_id": 999})

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Image not found"


async def test_saucenao_search_file_not_on_disk_returns_404(client):
    """When the blob file does not exist on disk, endpoint must return 404."""
    blob = _make_blob()
    mock_session = _make_mock_session(blob=blob)
    path_mock = _make_path_mock(exists=False)

    with (
        patch("routers.saucenao.get_credential", AsyncMock(return_value="api-key")),
        patch("routers.saucenao.async_session", mock_session),
        patch("routers.saucenao.resolve_blob_path", return_value=path_mock),
    ):
        resp = await client.post("/api/saucenao/search", json={"image_id": 1})

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Image file not found on disk"


async def test_saucenao_search_small_file_success_returns_200(client):
    """Small file (< 15MB) must be read directly and return 200 with results."""
    blob = _make_blob()
    mock_session = _make_mock_session(blob=blob)
    path_mock = _make_path_mock(exists=True, size=1024)
    expected_results = [{"similarity": "95.00", "title": "Test Image"}]
    mock_search = AsyncMock(return_value=expected_results)

    with (
        patch("routers.saucenao.get_credential", AsyncMock(return_value="api-key")),
        patch("routers.saucenao.async_session", mock_session),
        patch("routers.saucenao.resolve_blob_path", return_value=path_mock),
        patch("routers.saucenao.search_by_image", mock_search),
    ):
        resp = await client.post("/api/saucenao/search", json={"image_id": 1})

    assert resp.status_code == 200
    data = resp.json()
    assert data["results"] == expected_results
    mock_search.assert_called_once_with(
        b"fake-image-data",
        "api-key",
        filename="abc123.jpg",
    )


async def test_saucenao_search_large_file_resizes_before_search(client):
    """File > 15MB must be resized via PIL before being sent to SauceNAO."""
    blob = _make_blob()
    mock_session = _make_mock_session(blob=blob)
    _15mb = 15 * 1024 * 1024
    path_mock = _make_path_mock(exists=True, size=_15mb + 1)

    # Build a fake PIL image that PIL.Image.open returns as context manager
    fake_img = MagicMock()
    fake_img.__enter__ = MagicMock(return_value=fake_img)
    fake_img.__exit__ = MagicMock(return_value=False)
    fake_img.mode = "RGB"
    fake_img.thumbnail = MagicMock()

    resized_bytes = b"resized-jpeg-data"

    def _fake_save(buf, format=None, quality=None):  # noqa: ARG001
        buf.write(resized_bytes)

    fake_img.save = MagicMock(side_effect=_fake_save)

    mock_search = AsyncMock(return_value=[])

    with (
        patch("routers.saucenao.get_credential", AsyncMock(return_value="api-key")),
        patch("routers.saucenao.async_session", mock_session),
        patch("routers.saucenao.resolve_blob_path", return_value=path_mock),
        patch("routers.saucenao.PILImage.open", return_value=fake_img),
        patch("routers.saucenao.search_by_image", mock_search),
    ):
        resp = await client.post("/api/saucenao/search", json={"image_id": 1})

    assert resp.status_code == 200
    # PIL resize path must have been exercised
    fake_img.thumbnail.assert_called_once_with((2000, 2000))
    # search_by_image was called with resized bytes (not original)
    call_args = mock_search.call_args
    assert call_args[0][0] == resized_bytes


async def test_saucenao_search_rate_limit_error_returns_429(client):
    """RateLimitError from search_by_image must map to HTTP 429."""
    blob = _make_blob()
    mock_session = _make_mock_session(blob=blob)
    path_mock = _make_path_mock(exists=True, size=1024)

    with (
        patch("routers.saucenao.get_credential", AsyncMock(return_value="api-key")),
        patch("routers.saucenao.async_session", mock_session),
        patch("routers.saucenao.resolve_blob_path", return_value=path_mock),
        patch(
            "routers.saucenao.search_by_image",
            AsyncMock(side_effect=RateLimitError("too many requests")),
        ),
    ):
        resp = await client.post("/api/saucenao/search", json={"image_id": 1})

    assert resp.status_code == 429
    assert resp.json()["detail"] == "rate_limit"


async def test_saucenao_search_saucenao_error_returns_502(client):
    """SauceNaoError from search_by_image must map to HTTP 502."""
    blob = _make_blob()
    mock_session = _make_mock_session(blob=blob)
    path_mock = _make_path_mock(exists=True, size=1024)

    with (
        patch("routers.saucenao.get_credential", AsyncMock(return_value="api-key")),
        patch("routers.saucenao.async_session", mock_session),
        patch("routers.saucenao.resolve_blob_path", return_value=path_mock),
        patch(
            "routers.saucenao.search_by_image",
            AsyncMock(side_effect=SauceNaoError("upstream error")),
        ),
    ):
        resp = await client.post("/api/saucenao/search", json={"image_id": 1})

    assert resp.status_code == 502
    assert resp.json()["detail"] == "saucenao_error"


async def test_saucenao_search_httpx_error_returns_502(client):
    """httpx.HTTPError from search_by_image must map to HTTP 502."""
    blob = _make_blob()
    mock_session = _make_mock_session(blob=blob)
    path_mock = _make_path_mock(exists=True, size=1024)

    with (
        patch("routers.saucenao.get_credential", AsyncMock(return_value="api-key")),
        patch("routers.saucenao.async_session", mock_session),
        patch("routers.saucenao.resolve_blob_path", return_value=path_mock),
        patch(
            "routers.saucenao.search_by_image",
            AsyncMock(side_effect=httpx.HTTPError("connection failed")),
        ),
    ):
        resp = await client.post("/api/saucenao/search", json={"image_id": 1})

    assert resp.status_code == 502
    assert resp.json()["detail"] == "saucenao_error"
