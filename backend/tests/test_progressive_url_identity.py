"""ensure_gallery_from_identity: the URL decides the gallery, metadata only decorates it (ADR 0016).

The upsert uses ``pg_insert ... on_conflict_do_update`` which SQLite cannot run, so
these tests capture the statement sent to a mocked session and assert on the
compiled PostgreSQL values / ON CONFLICT SET clause instead of querying a DB.
"""

import re
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.dialects import postgresql

from plugins.builtin.gallery_dl._identity import UrlIdentity

_TWEET_META = {
    "category": "twitter",
    "subcategory": "media",
    "tweet_id": 111,
    "author": {"name": "cafu0425"},
    "user": {"name": "cafu0425"},
    "content": "hello #cosplay",
}


class _Harness:
    """Builds importers wired to a mocked session that records the upsert."""

    def __init__(self):
        self.statements: list = []
        self.tag_calls: list = []

    def make(self, source_url: str):
        from worker.progressive import ProgressiveImporter

        importer = ProgressiveImporter(db_job_id=None, user_id=None)
        importer.source_url = source_url
        importer._detect_trashed_conflict = AsyncMock(return_value=None)
        importer._load_gallery_state = AsyncMock()
        return importer

    def session_factory(self):
        harness = self

        async def _execute(stmt, *a, **kw):
            harness.statements.append(stmt)
            result = MagicMock()
            result.scalar_one.return_value = 42
            return result

        @asynccontextmanager
        async def _cm():
            session = MagicMock()
            session.execute = AsyncMock(side_effect=_execute)
            session.commit = AsyncMock()
            session.get = AsyncMock(return_value=None)
            yield session

        return lambda: _cm()

    async def run(self, importer, identity, metadata, dest=Path("/tmp/job")):
        async def _tags(session, gallery_id, tags):
            self.tag_calls.append((gallery_id, list(tags)))

        with (
            patch("worker.progressive.AsyncSessionLocal", self.session_factory()),
            patch("worker.progressive.upsert_metadata_gallery_tags", _tags),
        ):
            return await importer.ensure_gallery_from_identity(identity, metadata, dest)

    def last(self):
        compiled = self.statements[-1].compile(dialect=postgresql.dialect())
        return compiled.params, str(compiled)


@pytest.fixture
def harness():
    return _Harness()


@pytest.mark.asyncio
async def test_metadata_tweet_id_does_not_split_an_account_gallery_per_tweet(harness):
    identity = UrlIdentity("twitter", "cafu0425", True, "twitter")

    await harness.run(harness.make("https://x.com/cafu0425/media"), identity, _TWEET_META)
    first, _ = harness.last()
    await harness.run(
        harness.make("https://x.com/cafu0425/media"),
        identity,
        {**_TWEET_META, "tweet_id": 222},
        Path("/tmp/job2"),
    )
    second, _ = harness.last()

    for params in (first, second):
        assert (params["source"], params["source_id"]) == ("twitter", "cafu0425")
        assert params["artist_id"] == "twitter:cafu0425"
    assert "222" not in str(second["source_id"]) and "111" not in str(first["source_id"])


@pytest.mark.asyncio
async def test_one_posts_hashtags_and_text_do_not_become_the_account_gallerys_title_and_tags(harness):
    importer = harness.make("https://x.com/cafu0425/media")
    gid = await harness.run(importer, UrlIdentity("twitter", "cafu0425", True, "twitter"), _TWEET_META)

    params, sql = harness.last()
    assert gid == 42
    assert params["title"] == "cafu0425"
    assert not params["tags_array"]
    assert harness.tag_calls == []
    # Re-attaching to an existing account gallery must not overwrite its title/tags.
    set_clause = sql.split("DO UPDATE SET", 1)[1]
    assert not re.search(r"\btitle\s*=", set_clause)
    assert "tags_array" not in set_clause


@pytest.mark.asyncio
async def test_single_post_gallery_takes_its_artist_from_metadata_not_from_its_own_id(harness):
    importer = harness.make("https://x.com/cafu0425/status/111")
    await harness.run(importer, UrlIdentity("twitter", "tweet=cafu0425/111", False, "twitter"), _TWEET_META)

    params, _ = harness.last()
    assert params["source_id"] == "tweet=cafu0425/111"
    assert params["artist_id"] == "twitter:cafu0425"


@pytest.mark.asyncio
async def test_non_account_gallery_without_metadata_has_no_artist_rather_than_itself(harness):
    importer = harness.make("https://x.com/search?q=cat")
    await harness.run(importer, UrlIdentity("twitter", "search=cat", False, "twitter"), None)

    params, _ = harness.last()
    assert params["source_id"] == "search=cat"
    assert params["artist_id"] is None
    assert params["title"] == "search=cat"


@pytest.mark.asyncio
async def test_work_type_site_keeps_the_title_from_metadata(harness):
    importer = harness.make("https://nhentai.net/g/123456/")
    await harness.run(
        importer,
        UrlIdentity("nhentai", "gallery=123456", False, "nhentai"),
        {"category": "nhentai", "gallery_id": 123456, "title": "Some Book", "tags": ["artist:x"]},
    )

    params, _ = harness.last()
    assert params["title"] == "Some Book"
    assert (params["source"], params["source_id"]) == ("nhentai", "gallery=123456")


_COLLAB_POST_META = {"category": "instagram", "subcategory": "user", "username": "mancity", "fullname": "Man City"}


@pytest.mark.asyncio
async def test_account_gallery_does_not_take_its_uploader_from_a_collab_post_owned_by_someone_else(harness):
    """instagram/o4.18 got uploader "mancity": its first file was a collab post."""
    importer = harness.make("https://www.instagram.com/o4.18")
    await harness.run(importer, UrlIdentity("instagram", "o4.18", True, "instagram"), _COLLAB_POST_META)

    params, _ = harness.last()
    assert params["uploader"] == ""
    assert params["artist_id"] == "instagram:o4.18"


@pytest.mark.asyncio
async def test_single_post_gallery_still_takes_its_uploader_from_metadata(harness):
    importer = harness.make("https://www.instagram.com/p/Cabc/")
    await harness.run(importer, UrlIdentity("instagram", "post=Cabc", False, "instagram"), _COLLAB_POST_META)

    params, _ = harness.last()
    assert params["uploader"] == "mancity"
