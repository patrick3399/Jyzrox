"""Regression: archive entries are linked to the gallery whose job wrote them.

gallery-dl writes one archive row per downloaded file on its own connection,
with nothing but the ``entry`` column. Two downloads of one site share a table
and overlap by default (per-site concurrency is 2), so "every unlinked row
written while this job ran" also covers the other job's rows. Linking them to
the wrong gallery breaks both deletes: the victim's rows survive its deletion
(a re-download then skips those files as already archived) and vanish when the
other gallery is deleted.

Needs real Postgres (BE-T25) — column defaults, session settings and the
cascade are invisible to the SQLite suite. Skipped unless a server is given:

    docker run -d --rm --name jyzrox-test-pg -e POSTGRES_PASSWORD=test \
        -p 127.0.0.1:55432:5432 --tmpfs /var/lib/postgresql postgres:18-alpine
    JYZROX_TEST_PG_DSN=postgresql://postgres:test@127.0.0.1:55432/postgres \
        .venv/bin/pytest tests/test_archive_linking_pg.py

Each test creates and drops its own database on that server.
"""

import json
import os
import re
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

_ADMIN_DSN = os.environ.get("JYZROX_TEST_PG_DSN")

pytestmark = pytest.mark.skipif(not _ADMIN_DSN, reason="JYZROX_TEST_PG_DSN is not set")

_INIT_SQL = (Path(__file__).resolve().parent.parent.parent / "db" / "init.sql").read_text(encoding="utf-8")
_ARCHIVE_TABLE_RE = re.compile(r"CREATE TABLE IF NOT EXISTS \w+ \(\s*entry\s+TEXT PRIMARY KEY.*?\);", re.DOTALL)


@pytest.fixture
async def pg_dsn():
    """A fresh database holding ``galleries`` and the archive tables from init.sql."""
    import asyncpg

    name = f"jyzrox_archive_test_{uuid.uuid4().hex[:12]}"
    admin = await asyncpg.connect(_ADMIN_DSN)
    await admin.execute(f'CREATE DATABASE "{name}"')
    dsn = f"{_ADMIN_DSN.rsplit('/', 1)[0]}/{name}"
    try:
        conn = await asyncpg.connect(dsn)
        try:
            await conn.execute("CREATE TABLE galleries (id BIGINT PRIMARY KEY)")
            for ddl in _ARCHIVE_TABLE_RE.findall(_INIT_SQL):
                await conn.execute(ddl)
        finally:
            await conn.close()
        yield dsn
    finally:
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await admin.close()


@pytest.fixture
async def db(pg_dsn):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(pg_dsn.replace("postgresql://", "postgresql+asyncpg://", 1))
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


@pytest.fixture
def archive_dsn_for(pg_dsn, tmp_path):
    """The archive DSN the generated gallery-dl config hands to a job."""
    from tests.helpers import make_mock_site_config_svc

    async def _dsn(job_id: str | None) -> str:
        with (
            patch("plugins.builtin.gallery_dl.source.settings") as mock_settings,
            patch("core.site_config.site_config_service", make_mock_site_config_svc()),
        ):
            mock_settings.data_gallery_path = "/data/download_temp"
            mock_settings.gallery_dl_config = str(tmp_path / "gallery-dl.json")
            mock_settings.gdl_archive_dsn = pg_dsn
            from plugins.builtin.gallery_dl.source import _build_gallery_dl_config

            path = await _build_gallery_dl_config({}, config_id=job_id)
        return json.loads(path.read_text())["extractor"]["archive"]

    return _dsn


class _GalleryDl:
    """What a gallery-dl process does to the archive: its own connection, entry only."""

    def __init__(self, conn, table: str):
        self._conn = conn
        self._table = table

    @classmethod
    async def start(cls, dsn: str, table: str) -> _GalleryDl:
        import asyncpg

        return cls(await asyncpg.connect(dsn), table)

    async def archive(self, *entries: str) -> None:
        for entry in entries:
            # gallery_dl.archive.DownloadArchivePostgresql._stmt_insert, verbatim
            await self._conn.execute(f'INSERT INTO "{self._table}" (entry) VALUES ($1) ON CONFLICT DO NOTHING', entry)

    async def exit(self) -> None:
        await self._conn.close()


def _importer(job_id: str | None, gallery_id: int, source: str, source_id: str | None):
    from worker.progressive import ProgressiveImporter

    importer = ProgressiveImporter(job_id, None)
    importer.gallery_id = gallery_id
    importer.source = source
    importer.source_id = source_id
    return importer


async def _add_galleries(db, *gallery_ids: int) -> None:
    from sqlalchemy import text

    async with db() as session:
        for gallery_id in gallery_ids:
            await session.execute(text("INSERT INTO galleries (id) VALUES (:id)"), {"id": gallery_id})
        await session.commit()


async def _link(db, importer) -> None:
    async with db() as session:
        await importer._link_archive_entries(session)
        await session.commit()


async def _owners(db, table: str) -> dict[str, int | None]:
    from sqlalchemy import text

    async with db() as session:
        rows = await session.execute(text(f'SELECT entry, gallery_id FROM "{table}"'))
        return {entry: gallery_id for entry, gallery_id in rows}


async def _delete_gallery(db, gallery_id: int) -> None:
    from sqlalchemy import text

    async with db() as session:
        await session.execute(text("DELETE FROM galleries WHERE id = :id"), {"id": gallery_id})
        await session.commit()


async def test_job_finalizing_while_another_job_downloads_does_not_claim_its_rows(db, archive_dsn_for):
    job_a, job_b = str(uuid.uuid4()), str(uuid.uuid4())
    await _add_galleries(db, 1, 2)

    importer_a = _importer(job_a, 1, "twitter", "alice")
    gdl_a = await _GalleryDl.start(await archive_dsn_for(job_a), "twitter")
    importer_b = _importer(job_b, 2, "twitter", "bob")
    gdl_b = await _GalleryDl.start(await archive_dsn_for(job_b), "twitter")

    await gdl_a.archive("1700000000000000001_0_1")
    await gdl_b.archive("1800000000000000001_0_1", "1800000000000000002_0_1")
    await gdl_a.archive("1700000000000000002_0_1")
    await gdl_a.exit()

    # A finishes first; B is still downloading.
    await _link(db, importer_a)
    assert await _owners(db, "twitter") == {
        "1700000000000000001_0_1": 1,
        "1700000000000000002_0_1": 1,
        "1800000000000000001_0_1": None,
        "1800000000000000002_0_1": None,
    }

    await gdl_b.archive("1800000000000000003_0_1")
    await gdl_b.exit()
    await _link(db, importer_b)
    assert await _owners(db, "twitter") == {
        "1700000000000000001_0_1": 1,
        "1700000000000000002_0_1": 1,
        "1800000000000000001_0_1": 2,
        "1800000000000000002_0_1": 2,
        "1800000000000000003_0_1": 2,
    }

    # Deleting B frees every one of B's files for a re-download and none of A's.
    await _delete_gallery(db, 2)
    assert set(await _owners(db, "twitter")) == {"1700000000000000001_0_1", "1700000000000000002_0_1"}


async def test_rows_written_in_the_job_window_by_someone_else_are_left_unlinked(db, pg_dsn, archive_dsn_for):
    """A cancelled or failed job never links its rows; a neighbour must not adopt them."""
    job_a = str(uuid.uuid4())
    await _add_galleries(db, 1)

    importer_a = _importer(job_a, 1, "twitter", "alice")
    gdl_a = await _GalleryDl.start(await archive_dsn_for(job_a), "twitter")
    gdl_cancelled = await _GalleryDl.start(await archive_dsn_for(str(uuid.uuid4())), "twitter")
    gdl_untracked = await _GalleryDl.start(pg_dsn, "twitter")

    await gdl_a.archive("1700000000000000001_0_1")
    await gdl_cancelled.archive("1900000000000000001_0_1")
    await gdl_untracked.archive("1600000000000000001_0_1")
    for gdl in (gdl_a, gdl_cancelled, gdl_untracked):
        await gdl.exit()

    await _link(db, importer_a)
    assert await _owners(db, "twitter") == {
        "1700000000000000001_0_1": 1,
        "1900000000000000001_0_1": None,
        "1600000000000000001_0_1": None,
    }


async def test_retried_job_links_the_rows_its_earlier_attempt_wrote(db, archive_dsn_for):
    """A retry keeps the job id but builds a new importer, so its clock restarts."""
    job = str(uuid.uuid4())
    await _add_galleries(db, 1)

    first_attempt = await _GalleryDl.start(await archive_dsn_for(job), "twitter")
    await first_attempt.archive("1700000000000000001_0_1")
    await first_attempt.exit()

    importer = _importer(job, 1, "twitter", "alice")
    second_attempt = await _GalleryDl.start(await archive_dsn_for(job), "twitter")
    await second_attempt.archive("1700000000000000002_0_1")
    await second_attempt.exit()

    await _link(db, importer)
    assert await _owners(db, "twitter") == {"1700000000000000001_0_1": 1, "1700000000000000002_0_1": 1}


async def test_identity_prefix_does_not_claim_a_longer_id_that_starts_the_same(db, pg_dsn):
    """``gallery=12345`` must not adopt ``gallery=123456_1``."""
    await _add_galleries(db, 1)
    legacy = await _GalleryDl.start(pg_dsn, "xiuren7")
    await legacy.archive("gallery=12345_1", "gallery=12345_2", "gallery=123456_1", "gallery=12345")
    await legacy.exit()

    await _link(db, _importer(str(uuid.uuid4()), 1, "xiuren7", "gallery=12345"))
    assert await _owners(db, "xiuren7") == {
        "gallery=12345_1": 1,
        "gallery=12345_2": 1,
        "gallery=12345": 1,
        "gallery=123456_1": None,
    }


async def test_identity_prefix_followed_by_a_non_ascii_letter_is_a_different_id(db, pg_dsn):
    await _add_galleries(db, 1)
    legacy = await _GalleryDl.start(pg_dsn, "twitter")
    await legacy.archive("tag=猫_1", "tag=猫耳_1")
    await legacy.exit()

    await _link(db, _importer(str(uuid.uuid4()), 1, "twitter", "tag=猫"))
    assert await _owners(db, "twitter") == {"tag=猫_1": 1, "tag=猫耳_1": None}


async def test_identity_prefix_with_like_wildcards_is_matched_literally(db, pg_dsn):
    """An account named ``ab_cd`` or ``100%`` is text, not a LIKE pattern."""
    await _add_galleries(db, 1, 2)
    legacy = await _GalleryDl.start(pg_dsn, "twitter")
    await legacy.archive("abXcd_0_1", "ab_cd_0_1", "100200_0_1", "100%_0_1")
    await legacy.exit()

    await _link(db, _importer(str(uuid.uuid4()), 1, "twitter", "ab_cd"))
    await _link(db, _importer(str(uuid.uuid4()), 2, "twitter", "100%"))
    assert await _owners(db, "twitter") == {
        "abXcd_0_1": None,
        "ab_cd_0_1": 1,
        "100200_0_1": None,
        "100%_0_1": 2,
    }


async def test_numeric_account_name_does_not_claim_tweet_ids_that_start_with_it(db, pg_dsn):
    """A handle like ``17`` used to adopt every unlinked ``17…`` tweet on the site."""
    await _add_galleries(db, 1)
    other = await _GalleryDl.start(pg_dsn, "twitter")
    await other.archive("1700000000000000001_0_1", "1700000000000000002_0_1")
    await other.exit()

    await _link(db, _importer(str(uuid.uuid4()), 1, "twitter", "17"))
    assert await _owners(db, "twitter") == {"1700000000000000001_0_1": None, "1700000000000000002_0_1": None}


async def _job_id_defaults(db) -> dict[str, str | None]:
    from sqlalchemy import text

    async with db() as session:
        rows = await session.execute(
            text(
                "SELECT table_name, column_default FROM information_schema.columns "
                "WHERE table_schema = 'public' AND column_name = 'job_id'"
            )
        )
        return dict(rows.all())


async def test_migration_0032_stamps_tables_built_before_it_and_only_archive_tables(db, pg_dsn):
    import importlib.util

    from sqlalchemy import text

    path = Path(__file__).resolve().parent.parent / "migrations" / "versions" / "0032_archive_rows_record_their_job.py"
    spec = importlib.util.spec_from_file_location("migration_0032", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    statements: list[str] = []
    module.op = type("Op", (), {"execute": staticmethod(statements.append)})

    async def run(step) -> None:
        statements.clear()
        step()
        async with db() as session:
            for statement in statements:
                await session.execute(text(statement))
            await session.commit()

    async with db() as session:
        # The schema as migration 0031 left it, plus a look-alike that is not an archive table.
        await session.execute(text("ALTER TABLE twitter ALTER COLUMN job_id DROP DEFAULT"))
        await session.execute(text("ALTER TABLE xiuren7 ALTER COLUMN job_id DROP DEFAULT"))
        await session.execute(
            text(
                "CREATE TABLE lookalike (entry TEXT, gallery_id BIGINT, job_id UUID, created_at TIMESTAMPTZ, note TEXT)"
            )
        )
        await session.commit()

    await run(module.upgrade)
    await run(module.upgrade)  # a database built from the current init.sql is already there

    defaults = await _job_id_defaults(db)
    assert defaults.pop("lookalike") is None
    assert len(defaults) >= 14
    assert all(default and "jyzrox.archive_job_id" in default for default in defaults.values()), defaults

    job = str(uuid.uuid4())
    gdl = await _GalleryDl.start(f"{pg_dsn}?options=-c%20jyzrox.archive_job_id%3D{job}", "twitter")
    await gdl.archive("1700000000000000001_0_1")
    await gdl.exit()
    async with db() as session:
        stamped = (await session.execute(text("SELECT job_id FROM twitter"))).scalar_one()
    assert str(stamped) == job

    await run(module.downgrade)
    assert set((await _job_id_defaults(db)).values()) == {None}


async def test_table_gallery_dl_created_itself_is_stamped_once_the_worker_upgrades_it(db, pg_dsn, archive_dsn_for):
    """An unregistered category gets ``(entry TEXT PRIMARY KEY)`` from gallery-dl."""
    from sqlalchemy import text

    import worker

    async with db() as session:
        await session.execute(text("CREATE TABLE newsite (entry TEXT PRIMARY KEY)"))
        await session.execute(text("INSERT INTO newsite (entry) VALUES ('before-upgrade')"))
        await session.commit()

    with patch("core.database.AsyncSessionLocal", db):
        await worker._ensure_archive_table_schema()

    job = str(uuid.uuid4())
    gdl = await _GalleryDl.start(await archive_dsn_for(job), "newsite")
    await gdl.archive("after-upgrade")
    await gdl.exit()

    async with db() as session:
        rows = dict((await session.execute(text("SELECT entry, job_id::text FROM newsite"))).all())
    assert rows == {"before-upgrade": None, "after-upgrade": job}


async def test_unregistered_category_rows_are_linked_and_cascade_with_the_gallery(db, pg_dsn, archive_dsn_for):
    """Regression: the table resolved to "gallery_dl" for a category outside GDL_SITES."""
    from sqlalchemy import text

    import worker

    async with db() as session:
        await session.execute(text("CREATE TABLE newsite (entry TEXT PRIMARY KEY)"))
        await session.commit()
    with patch("core.database.AsyncSessionLocal", db):
        await worker._ensure_archive_table_schema()

    job = str(uuid.uuid4())
    await _add_galleries(db, 1)
    gdl = await _GalleryDl.start(await archive_dsn_for(job), "newsite")
    await gdl.archive("gallery=42_1", "gallery=42_2")
    await gdl.exit()

    await _link(db, _importer(job, 1, "newsite", "gallery=42"))
    assert await _owners(db, "newsite") == {"gallery=42_1": 1, "gallery=42_2": 1}

    await _delete_gallery(db, 1)
    assert await _owners(db, "newsite") == {}


async def test_source_naming_a_non_archive_table_never_updates_it(db, pg_dsn):
    """The table name now comes from the gallery's source: only archive tables qualify."""
    from sqlalchemy import text

    job = str(uuid.uuid4())
    await _add_galleries(db, 1)
    async with db() as session:
        await session.execute(text("CREATE TABLE notes (id INT PRIMARY KEY, gallery_id BIGINT, job_id UUID)"))
        await session.execute(text("INSERT INTO notes VALUES (1, NULL, CAST(:j AS uuid))"), {"j": job})
        await session.commit()

    # No source_id: only the job_id statement runs, which such a table satisfies.
    await _link(db, _importer(job, 1, "notes", None))

    async with db() as session:
        assert (await session.execute(text("SELECT gallery_id FROM notes"))).scalar() is None


async def test_eh_rows_written_to_the_exhentai_table_are_linked_and_cascade(db, archive_dsn_for):
    """Regression: an "ehentai" gallery looked for an "ehentai" table, which does not exist.

    gallery-dl runs e-hentai.org and exhentai.org under one category, "exhentai",
    so the rows land in that table and were never linked. They outlived the
    gallery and a re-download skipped those files as already archived.
    """
    job = str(uuid.uuid4())
    await _add_galleries(db, 1)
    gdl = await _GalleryDl.start(await archive_dsn_for(job), "exhentai")
    await gdl.archive("exhentai1234567_1", "exhentai1234567_2")
    await gdl.exit()

    await _link(db, _importer(job, 1, "ehentai", "1234567"))
    assert await _owners(db, "exhentai") == {"exhentai1234567_1": 1, "exhentai1234567_2": 1}

    await _delete_gallery(db, 1)
    assert await _owners(db, "exhentai") == {}
