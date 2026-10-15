"""A run that fetched nothing must still point at the gallery it matched."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from worker.download import _link_already_saved_gallery

_IDENTITY = SimpleNamespace(source="xiuren7", source_id="gallery=430738", is_account=False, category="xiuren7")


def _session(gallery_row, job):
    result = MagicMock()
    result.one_or_none.return_value = gallery_row
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    session.get = AsyncMock(return_value=job)
    session.commit = AsyncMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return session, MagicMock(return_value=cm)


@pytest.mark.asyncio
async def test_all_skipped_run_links_existing_live_gallery_to_job():
    job = SimpleNamespace(gallery_id=None)
    row = SimpleNamespace(id=42, title="No.8984", pages=85)
    session, factory = _session(row, job)
    with (
        patch("core.database.AsyncSessionLocal", factory),
        patch("plugins.builtin.gallery_dl._identity.resolve_url_identity", return_value=_IDENTITY),
    ):
        got = await _link_already_saved_gallery(str(uuid.uuid4()), "http://www.xiuren7.com/430738.html", "gallery_dl")

    assert got == {"gallery_id": 42, "title": "No.8984", "pages": 85}
    assert job.gallery_id == 42
    session.commit.assert_awaited_once()
    # Trashed galleries must not be linked: the lookup has to filter deleted_at.
    assert "deleted_at IS NULL" in str(session.execute.call_args.args[0])


@pytest.mark.asyncio
async def test_all_skipped_run_without_matching_gallery_returns_none_and_leaves_job_unlinked():
    job = SimpleNamespace(gallery_id=None)
    session, factory = _session(None, job)
    with (
        patch("core.database.AsyncSessionLocal", factory),
        patch("plugins.builtin.gallery_dl._identity.resolve_url_identity", return_value=_IDENTITY),
    ):
        got = await _link_already_saved_gallery(str(uuid.uuid4()), "http://www.xiuren7.com/1.html", "gallery_dl")

    assert got is None
    assert job.gallery_id is None
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_account_level_url_is_not_linked_to_a_single_gallery():
    identity = SimpleNamespace(source="pixiv", source_id="123", is_account=True, category="pixiv")
    session, factory = _session(SimpleNamespace(id=1, title="x", pages=1), SimpleNamespace(gallery_id=None))
    with (
        patch("core.database.AsyncSessionLocal", factory),
        patch("plugins.builtin.gallery_dl._identity.resolve_url_identity", return_value=identity),
    ):
        got = await _link_already_saved_gallery(str(uuid.uuid4()), "https://www.pixiv.net/users/123", "gallery_dl")

    assert got is None
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_non_gallery_dl_plugin_is_never_resolved_by_url_identity():
    with patch("plugins.builtin.gallery_dl._identity.resolve_url_identity") as resolve:
        got = await _link_already_saved_gallery(str(uuid.uuid4()), "https://e-hentai.org/g/1/a/", "ehentai")

    assert got is None
    resolve.assert_not_called()
