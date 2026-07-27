"""Regression tests for the 0021 external-location backfill.

The first version bound every Image of a shared sha256 to the single
``Blob.external_path``, which silently collapsed distinct source files onto one
location. On the live DB that was 142 images across 136 hashes. These tests
execute the migration's real statements (imported, not copied) against SQLite.
"""

import importlib.util
import sqlite3
from pathlib import Path

import pytest

_MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "versions" / "0021_blob_locations.py"

# Mirrors the columns the backfill touches, with SQLite-compatible types.
_SCHEMA = """
CREATE TABLE galleries (
    id INTEGER PRIMARY KEY,
    source_path TEXT
);
CREATE TABLE blobs (
    sha256 TEXT PRIMARY KEY,
    storage TEXT NOT NULL,
    external_path TEXT
);
CREATE TABLE blob_locations (
    blob_sha256 TEXT NOT NULL REFERENCES blobs(sha256) ON DELETE CASCADE,
    external_path TEXT NOT NULL,
    PRIMARY KEY (blob_sha256, external_path)
);
CREATE TABLE images (
    id INTEGER PRIMARY KEY,
    gallery_id INTEGER NOT NULL REFERENCES galleries(id),
    filename TEXT,
    blob_sha256 TEXT NOT NULL REFERENCES blobs(sha256),
    external_path TEXT
);
"""


def _backfill_statements() -> tuple[str, ...]:
    """Import the migration module directly (its filename is not importable)."""
    spec = importlib.util.spec_from_file_location("migration_0021", _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.BACKFILL_STATEMENTS


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.executescript(_SCHEMA)
    yield conn
    conn.close()


def _run_backfill(conn: sqlite3.Connection) -> None:
    for statement in _backfill_statements():
        conn.execute(statement)


def test_shared_sha_across_galleries_keeps_each_images_own_path(db):
    """The bug: two galleries linking byte-identical files at different paths.

    Both Images share one sha256, so the per-Blob backfill pointed both at
    whichever path ``Blob.external_path`` happened to hold — making gallery A
    depend on gallery B's file.
    """
    db.executescript("""
        INSERT INTO galleries (id, source_path) VALUES
            (1, '/mnt/lib/A'),
            (2, '/mnt/lib/B');
        -- one blob, and its scalar path points at gallery B's copy
        INSERT INTO blobs (sha256, storage, external_path) VALUES
            ('sha_dup', 'external', '/mnt/lib/B/pic.png');
        INSERT INTO images (id, gallery_id, filename, blob_sha256) VALUES
            (10, 1, 'pic.png', 'sha_dup'),
            (20, 2, 'pic.png', 'sha_dup');
    """)

    _run_backfill(db)

    bound = dict(db.execute("SELECT id, external_path FROM images ORDER BY id").fetchall())
    assert bound[10] == "/mnt/lib/A/pic.png", "gallery A's image must keep its own file"
    assert bound[20] == "/mnt/lib/B/pic.png"

    # Both locations must be registered, or the composite FK would reject them.
    locations = {row[0] for row in db.execute("SELECT external_path FROM blob_locations WHERE blob_sha256='sha_dup'")}
    assert locations == {"/mnt/lib/A/pic.png", "/mnt/lib/B/pic.png"}


def test_legacy_scalar_path_outside_source_dir_is_not_used(db):
    """A legacy path pointing outside the gallery's own source_path is wrong.

    Every mismatch measured on the live DB had this shape, so the derived path
    must win rather than the scalar.
    """
    db.executescript("""
        INSERT INTO galleries (id, source_path) VALUES (1, '/mnt/lib/own');
        INSERT INTO blobs (sha256, storage, external_path) VALUES
            ('sha_x', 'external', '/mnt/lib/somewhere-else/other.png');
        INSERT INTO images (id, gallery_id, filename, blob_sha256) VALUES
            (1, 1, 'own.png', 'sha_x');
    """)

    _run_backfill(db)

    (path,) = db.execute("SELECT external_path FROM images WHERE id=1").fetchone()
    assert path == "/mnt/lib/own/own.png"


def test_unreconstructable_row_falls_back_to_legacy_scalar(db):
    """No source_path (or no filename) → the legacy scalar is all we have."""
    db.executescript("""
        INSERT INTO galleries (id, source_path) VALUES (1, NULL), (2, '/mnt/lib/C');
        INSERT INTO blobs (sha256, storage, external_path) VALUES
            ('sha_nopath', 'external', '/mnt/legacy/a.png'),
            ('sha_noname', 'external', '/mnt/legacy/b.png');
        INSERT INTO images (id, gallery_id, filename, blob_sha256) VALUES
            (1, 1, 'a.png', 'sha_nopath'),
            (2, 2, NULL,    'sha_noname');
    """)

    _run_backfill(db)

    bound = dict(db.execute("SELECT id, external_path FROM images ORDER BY id").fetchall())
    assert bound[1] == "/mnt/legacy/a.png"
    assert bound[2] == "/mnt/legacy/b.png"


def test_cas_blobs_are_left_unbound(db):
    """Only external storage gets a location; CAS rows must stay NULL so the
    composite FK (MATCH SIMPLE) stays satisfied without a parent row."""
    db.executescript("""
        INSERT INTO galleries (id, source_path) VALUES (1, '/mnt/lib/A');
        INSERT INTO blobs (sha256, storage, external_path) VALUES ('sha_cas', 'cas', NULL);
        INSERT INTO images (id, gallery_id, filename, blob_sha256) VALUES (1, 1, 'p.png', 'sha_cas');
    """)

    _run_backfill(db)

    (path,) = db.execute("SELECT external_path FROM images WHERE id=1").fetchone()
    assert path is None
    assert db.execute("SELECT count(*) FROM blob_locations").fetchone()[0] == 0


def test_every_bound_path_has_a_blob_locations_parent(db):
    """The composite FK is added right after the backfill, so any Image path
    without a matching blob_locations row would abort the migration."""
    db.executescript("""
        INSERT INTO galleries (id, source_path) VALUES (1, '/mnt/lib/A'), (2, NULL);
        INSERT INTO blobs (sha256, storage, external_path) VALUES
            ('sha_a', 'external', '/mnt/lib/A/one.png'),
            ('sha_b', 'external', '/mnt/legacy/two.png');
        INSERT INTO images (id, gallery_id, filename, blob_sha256) VALUES
            (1, 1, 'one.png', 'sha_a'),
            (2, 1, 'extra.png', 'sha_a'),
            (3, 2, 'two.png', 'sha_b');
    """)

    _run_backfill(db)

    orphans = db.execute("""
        SELECT i.id FROM images i
        WHERE i.external_path IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM blob_locations l
            WHERE l.blob_sha256 = i.blob_sha256 AND l.external_path = i.external_path
          )
    """).fetchall()
    assert orphans == []
