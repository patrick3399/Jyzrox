#!/usr/bin/env python3
"""One-off migration: insert a category level into the local library layout.

This is an operator script, not an Alembic revision: the artist->category
mapping is site-specific data, so it must never run as part of a deployment.

It preserves gallery identity. Every Gallery and Image row keeps its id; only
``source_id`` and the absolute-path columns are rewritten. That makes this the
bulk, offline equivalent of ``move_library_path_job`` (ADR 0009), which is
deliberately bypassed here: routing ~1.4k renames through the watcher would
hash every file and fall into ``ambiguous_content_match``.

Run order and location (both are forced by filesystem ownership -- the source
tree is host-owned and mounted read-only into the containers, while the
library tree is owned by the container uid and Postgres is not published to
the host):

    # 0. host: stop the writers, freeze the scheduled scan
    docker compose stop api worker
    redis-cli -a "$REDIS_PASSWORD" set cron:library_scan:enabled 0

    # 1. host: preview
    backend/.venv/bin/python scripts/migrate_local_category.py plan \\
        --mapping scripts/category-map.tsv --root /mnt/ssd-data/images

    # 2. host: rename the source tree
    backend/.venv/bin/python scripts/migrate_local_category.py move-source \\
        --mapping scripts/category-map.tsv --root /mnt/ssd-data/images

    # 3. container: rewrite the database and rebuild the library tree
    docker compose run --rm --no-deps -v "$PWD/scripts:/opsscripts:ro" \\
        --entrypoint python worker /opsscripts/migrate_local_category.py commit \\
        --mapping /opsscripts/category-map.tsv --root /mnt/ssd-data/images

    # 4. container: verify
    docker compose run --rm --no-deps -v "$PWD/scripts:/opsscripts:ro" \\
        --entrypoint python worker /opsscripts/migrate_local_category.py verify \\
        --mapping /opsscripts/category-map.tsv --root /mnt/ssd-data/images

``move-source`` is reversible with ``--reverse``. ``commit`` runs in a single
transaction and its library-tree rebuild is idempotent, so a failed run is
resumed by simply running it again.

``rebuild-tree`` re-runs only the library-tree half of ``commit`` (symlinks,
ownership markers, stale-sidecar cleanup, stale-dir prune) from the DB's
current state, without touching or validating ``--mapping``. Use it to resume
a ``commit`` that rewrote the database but didn't finish pruning, or any time
the library tree needs to be repaired to match the database:

    docker compose run --rm --no-deps --entrypoint python worker \\
        /opsscripts/migrate_local_category.py rebuild-tree \\
        --root /mnt/ssd-data/images [--max-stale N]

Round 2 -- ``recategorize-source`` / ``recategorize-commit`` move an artist
from one already-present category to another (fixing a wrong first-round
classification), instead of inserting a category segment for the first time.
Same run order and host/container split as round 1, same mapping file shape
(artist<TAB>target-category), and ``verify``/``rebuild-tree`` above are
reused as-is:

    # 0. host: stop the writers, freeze the scheduled scan (same as round 1)

    # 1. host: move the artist directory to its new category directory
    backend/.venv/bin/python scripts/migrate_local_category.py recategorize-source \\
        --mapping scripts/recategorize-map.tsv --root /mnt/ssd-data/images

    # 2. container: rewrite the database and rebuild the library tree
    docker compose run --rm --no-deps -v "$PWD/scripts:/opsscripts:ro" \\
        --entrypoint python worker /opsscripts/migrate_local_category.py recategorize-commit \\
        --mapping /opsscripts/recategorize-map.tsv --root /mnt/ssd-data/images

    # 3. container: verify (reuses the round-1 ``verify`` command)
"""

import argparse
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))
sys.path.insert(0, "/app")

from core.local_category_plan import (  # noqa: E402
    MigrationError,
    assert_safe_source_id_unique,
    load_mapping,
    safe_source_id,
    transform_source_id,
    validate_mapping,
)

# Default guard rail for the stale-library-dir sweep. This is only a coarse
# proxy for "the expected set looks sane" -- it does NOT by itself prove a dir
# is safe to delete. It exists so an operator must consciously raise
# --max-stale (rather than silently deleting a huge, possibly-wrong set) when
# a rebuild strategy legitimately produces more stale dirs than usual, e.g. a
# rename-style migration that creates ~1.4k new dirs before the old ones
# become unclaimed. The real safety property is enforced separately by
# ``_find_unsafe_regular_files``: every dir actually gets deleted only if it
# contains nothing but symlinks and the two known sidecar files.
_MAX_STALE_LIBRARY_DIRS = 300

# Sidecar filenames that are expected to be ordinary (non-symlink) files
# inside an otherwise symlink-only gallery dir.
_SAFE_NON_SYMLINK_NAMES = {"info.json", ".gallery-owner"}


@dataclass(frozen=True)
class SqlStatement:
    kind: str
    sql: str


def build_sql_statements() -> list[SqlStatement]:
    """Return the path-rewrite statements in FK-safe order.

    ``fk_images_blob_location`` (images -> blob_locations, composite, NOT
    deferrable) forces insert-before-update and update-before-delete.
    """
    return [
        SqlStatement(
            kind="insert_blob_locations",
            sql=(
                "INSERT INTO blob_locations (blob_sha256, external_path, created_at) "
                "SELECT blob_sha256, :root_prefix || :category || '/' || "
                "substring(external_path from char_length(:root_prefix) + 1), created_at "
                "FROM blob_locations "
                "WHERE starts_with(external_path, :root_prefix || :artist || '/') "
                "ON CONFLICT DO NOTHING"
            ),
        ),
        SqlStatement(
            kind="update_images",
            sql=(
                "UPDATE images SET external_path = :root_prefix || :category || '/' || "
                "substring(external_path from char_length(:root_prefix) + 1) "
                "WHERE starts_with(external_path, :root_prefix || :artist || '/')"
            ),
        ),
        SqlStatement(
            kind="delete_blob_locations",
            sql=(
                "DELETE FROM blob_locations "
                "WHERE starts_with(external_path, :root_prefix || :artist || '/') "
                "AND NOT EXISTS (SELECT 1 FROM images i WHERE i.blob_sha256 = blob_locations.blob_sha256 "
                "AND i.external_path = blob_locations.external_path)"
            ),
        ),
        SqlStatement(
            kind="update_blobs",
            sql=(
                "UPDATE blobs SET external_path = :root_prefix || :category || '/' || "
                "substring(external_path from char_length(:root_prefix) + 1) "
                "WHERE starts_with(external_path, :root_prefix || :artist || '/')"
            ),
        ),
        SqlStatement(
            kind="update_galleries",
            sql=(
                "UPDATE galleries SET "
                "source_id = :category || '/' || source_id, "
                "source_path = :root_prefix || :category || '/' || "
                "substring(source_path from char_length(:root_prefix) + 1), "
                "category = :category "
                "WHERE source = 'local' AND split_part(source_id, '/', 1) = :artist"
            ),
        ),
    ]


def build_recategorize_sql_statements() -> list[SqlStatement]:
    """Return the round-2 recategorize statements in FK-safe order.

    Same 5 kinds, same order and same non-deferrable-FK reasoning as
    ``build_sql_statements()``. The difference is that round 1 *inserts* a
    category segment in front of an artist-rooted path, while this replaces
    an already-present category segment (segment 0) with a new one, for
    paths already rooted at ``root_prefix/old_category/artist/``.

    Every WHERE clause uses ``starts_with()``, never ``LIKE``: an artist name
    containing ``_`` (e.g. ``Nai_奈緋``) is a SQL wildcard under ``LIKE`` and
    would silently over-match unrelated rows sharing the same prefix shape
    (round-1 regression, ~90k rows affected).
    """
    old_prefix = "(:root_prefix || :old_category || '/' || :artist || '/')"
    new_prefix = "(:root_prefix || :new_category || '/' || :artist || '/')"
    return [
        SqlStatement(
            kind="insert_blob_locations",
            sql=(
                "INSERT INTO blob_locations (blob_sha256, external_path, created_at) "
                f"SELECT blob_sha256, {new_prefix} || "
                f"substring(external_path from char_length({old_prefix}) + 1), created_at "
                "FROM blob_locations "
                f"WHERE starts_with(external_path, {old_prefix}) "
                "ON CONFLICT DO NOTHING"
            ),
        ),
        SqlStatement(
            kind="update_images",
            sql=(
                f"UPDATE images SET external_path = {new_prefix} || "
                f"substring(external_path from char_length({old_prefix}) + 1) "
                f"WHERE starts_with(external_path, {old_prefix})"
            ),
        ),
        SqlStatement(
            kind="delete_blob_locations",
            sql=(
                "DELETE FROM blob_locations "
                f"WHERE starts_with(external_path, {old_prefix}) "
                "AND NOT EXISTS (SELECT 1 FROM images i WHERE i.blob_sha256 = blob_locations.blob_sha256 "
                "AND i.external_path = blob_locations.external_path) "
                "AND EXISTS (SELECT 1 FROM blob_locations nb WHERE nb.blob_sha256 = blob_locations.blob_sha256 "
                f"AND nb.external_path = {new_prefix} || "
                f"substring(blob_locations.external_path from char_length({old_prefix}) + 1))"
            ),
        ),
        SqlStatement(
            kind="update_blobs",
            sql=(
                f"UPDATE blobs SET external_path = {new_prefix} || "
                f"substring(external_path from char_length({old_prefix}) + 1) "
                f"WHERE starts_with(external_path, {old_prefix})"
            ),
        ),
        SqlStatement(
            kind="update_galleries",
            sql=(
                "UPDATE galleries SET "
                f"source_id = :new_category || '/' || :artist || '/' || "
                "substring(source_id from char_length(:old_category || '/' || :artist || '/') + 1), "
                f"source_path = {new_prefix} || "
                f"substring(source_path from char_length({old_prefix}) + 1), "
                "category = :new_category "
                "WHERE source = 'local' AND split_part(source_id, '/', 1) = :old_category "
                "AND split_part(source_id, '/', 2) = :artist "
                "AND starts_with(source_id, :old_category || '/' || :artist || '/')"
            ),
        ),
    ]


def move_source_tree(root: str, mapping: dict[str, str], *, reverse: bool) -> list[tuple[str, str]]:
    """Move each artist directory under (or out of) its category directory."""
    root_path = Path(root)
    if not root_path.is_dir():
        raise MigrationError(f"library root is not a directory: {root}")

    moves: list[tuple[str, str]] = []
    for artist, category in sorted(mapping.items()):
        flat = root_path / artist
        nested = root_path / category / artist
        src, dst = (nested, flat) if reverse else (flat, nested)
        if not src.is_dir():
            raise MigrationError(f"missing artist directory: {src}")
        if dst.exists():
            raise MigrationError(f"destination already exists: {dst}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        os.rename(src, dst)
        moves.append((str(src), str(dst)))

    if reverse:
        for category in sorted(set(mapping.values())):
            category_dir = root_path / category
            if category_dir.is_dir() and not any(category_dir.iterdir()):
                category_dir.rmdir()
    return moves


def recategorize_source_tree(root: str, mapping: dict[str, str]) -> list[tuple[str, str]]:
    """Move each artist directory from its current category dir to its
    target category dir.

    ``mapping`` is artist -> target category. "Current" category is
    discovered by scanning one level of ``root`` for a category directory
    that contains an ``<artist>`` child; this fails closed (no guessing) if
    that search is ambiguous or comes up empty.
    """
    root_path = Path(root)
    if not root_path.is_dir():
        raise MigrationError(f"library root is not a directory: {root}")

    category_dirs = sorted(e.name for e in os.scandir(root_path) if e.is_dir(follow_symlinks=False))

    moves: list[tuple[str, str]] = []
    touched_categories: set[str] = set()
    for artist, target_category in sorted(mapping.items()):
        found = [c for c in category_dirs if (root_path / c / artist).is_dir()]
        already_at_target = target_category in found
        other = [c for c in found if c != target_category]
        if len(other) > 1:
            raise MigrationError(f"ambiguous current category for artist {artist!r}: found under {other}")

        dst = root_path / target_category / artist
        if already_at_target:
            if other:
                # Present under both its (single) current category and the
                # target -- moving would overwrite the target, so refuse
                # rather than guess which one is authoritative.
                raise MigrationError(f"destination already exists: {dst}")
            continue  # already in its target category: no-op, not an error
        if not other:
            raise MigrationError(f"artist directory not found under any category dir: {artist!r}")

        current_category = other[0]
        src = root_path / current_category / artist
        if dst.exists():
            raise MigrationError(f"destination already exists: {dst}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        os.rename(src, dst)
        moves.append((str(src), str(dst)))
        touched_categories.add(current_category)

    for category in sorted(touched_categories):
        category_dir = root_path / category
        if category_dir.is_dir() and not any(category_dir.iterdir()):
            category_dir.rmdir()
    return moves


def _find_unsafe_regular_files(dir_path: Path) -> list[Path]:
    """Return paths under ``dir_path`` that are neither a symlink nor an
    allow-listed sidecar file. A non-empty result means the dir holds real
    data and must not be deleted, regardless of the removal-count guard.
    """
    unsafe: list[Path] = []
    for root, _dirs, files in os.walk(dir_path, followlinks=False):
        root_path = Path(root)
        for name in files:
            if name in _SAFE_NON_SYMLINK_NAMES:
                continue
            file_path = root_path / name
            if not file_path.is_symlink():
                unsafe.append(file_path)
    return unsafe


def prune_stale_library_dirs(local_root: Path, expected: set[str], *, max_removals: int) -> list[str]:
    """Remove library dirs that no gallery claims. Fails closed on surprises."""
    if not expected:
        raise MigrationError("refusing to prune: expected set is empty")
    if not local_root.is_dir():
        raise MigrationError(f"refusing to prune: {local_root} is not a directory")

    stale = sorted(e.name for e in os.scandir(local_root) if e.is_dir(follow_symlinks=False) and e.name not in expected)
    if len(stale) > max_removals:
        raise MigrationError(
            f"refusing to remove {len(stale)} library dirs (limit {max_removals}); "
            "if you have confirmed the extra stale dirs are safe to delete, re-run with "
            "--max-stale N to raise the limit"
        )

    unsafe_files = [str(path) for name in stale for path in _find_unsafe_regular_files(local_root / name)]
    if unsafe_files:
        sample = ", ".join(unsafe_files[:5])
        more = f" (+{len(unsafe_files) - 5} more)" if len(unsafe_files) > 5 else ""
        raise MigrationError(
            f"refusing to remove {len(stale)} library dirs: found {len(unsafe_files)} non-symlink file(s) "
            f"other than {sorted(_SAFE_NON_SYMLINK_NAMES)}, e.g. {sample}{more}. "
            "These dirs may hold real data; investigate before deleting."
        )

    for name in stale:
        shutil.rmtree(local_root / name)
    return stale


# ---------------------------------------------------------------------------
# Database-backed phases (container only)
# ---------------------------------------------------------------------------


async def _load_local_galleries(session):
    from sqlalchemy import text as _text

    rows = await session.execute(_text("SELECT id, source_id FROM galleries WHERE source = 'local' ORDER BY id"))
    return [(row[0], row[1]) for row in rows]


async def _cmd_plan(args) -> int:
    from core.database import AsyncSessionLocal

    mapping = load_mapping(args.mapping)
    async with AsyncSessionLocal() as session:
        galleries = await _load_local_galleries(session)

    artists = {sid.split("/", 1)[0] for _, sid in galleries}
    validate_mapping(mapping, artists)
    new_ids = [transform_source_id(sid, mapping) for _, sid in galleries]
    assert_safe_source_id_unique(new_ids)

    per_category: dict[str, int] = {}
    for new_id in new_ids:
        category = new_id.split("/", 1)[0]
        per_category[category] = per_category.get(category, 0) + 1

    print(f"galleries: {len(galleries)}")
    print(f"artists:   {len(artists)}")
    for category, count in sorted(per_category.items(), key=lambda kv: -kv[1]):
        print(f"  {category:<20} {count:>6}")
    print("\nsample transforms:")
    for (_, old), new in list(zip(galleries, new_ids, strict=True))[:5]:
        print(f"  {old}\n    -> {new}")
    print("\nplan OK — no errors")
    return 0


async def _cmd_commit(args) -> int:
    from sqlalchemy import text as _text

    from core.database import AsyncSessionLocal

    mapping = load_mapping(args.mapping)
    root_prefix = args.root.rstrip("/") + "/"

    async with AsyncSessionLocal() as session:
        galleries = await _load_local_galleries(session)
        artists = {sid.split("/", 1)[0] for _, sid in galleries}
        validate_mapping(mapping, artists)
        assert_safe_source_id_unique([transform_source_id(sid, mapping) for _, sid in galleries])

        await session.execute(_text("SELECT pg_advisory_xact_lock(hashtext('jyzrox_local_category_migration'))"))

        for artist, category in sorted(mapping.items()):
            params = {"root_prefix": root_prefix, "artist": artist, "category": category}
            for stmt in build_sql_statements():
                result = await session.execute(_text(stmt.sql), params)
                print(f"  {artist:<28} {stmt.kind:<24} {result.rowcount:>7}")

        await session.execute(
            _text("UPDATE library_paths SET pattern = :pattern WHERE path = :path"),
            {"pattern": args.pattern, "path": args.root.rstrip("/")},
        )
        await session.commit()
    print("database committed")

    await _rebuild_library_tree(args)
    return 0


async def _cmd_recategorize_commit(args) -> int:
    """Round-2: move mapped artists from their current category to a new one.

    ``mapping`` here is artist -> target category, same TSV shape as round
    1's mapping. Unlike round 1, the DB is already migrated: ``source_id``
    is 4-segment ``{category}/{artist}/{_}/{title}``, so "current category"
    is read per-artist from the DB (``validate_mapping``/``transform_source_id``
    assume an un-migrated 3-segment, artist-rooted id and would misread the
    now-present category segment as an artist -- they are not reused here).
    """
    from sqlalchemy import text as _text

    from core.database import AsyncSessionLocal

    mapping = load_mapping(args.mapping)
    _validate_category_names_only(mapping)
    root_prefix = args.root.rstrip("/") + "/"

    async with AsyncSessionLocal() as session:
        galleries = await _load_local_galleries(session)

        current_category_by_artist: dict[str, str] = {}
        for _id, source_id in galleries:
            segments = source_id.split("/")
            if len(segments) != 4:
                raise MigrationError(f"expected 4 source_id segments, got {len(segments)}: {source_id!r}")
            category, artist = segments[0], segments[1]
            existing = current_category_by_artist.get(artist)
            if existing is not None and existing != category:
                raise MigrationError(
                    f"artist {artist!r} spans multiple current categories: {existing!r} and {category!r}"
                )
            current_category_by_artist[artist] = category

        missing = sorted(set(mapping) - set(current_category_by_artist))
        if missing:
            raise MigrationError(f"artists not found in database: {missing}")

        # Only artists that actually change category get a target; artists
        # already in their target category are a no-op (fine, not an error).
        moves = {
            artist: (current_category_by_artist[artist], target_category)
            for artist, target_category in mapping.items()
            if current_category_by_artist[artist] != target_category
        }
        target_by_artist = {artist: new_category for artist, (_old, new_category) in moves.items()}

        new_source_ids = []
        for _id, source_id in galleries:
            segments = source_id.split("/")
            new_category = target_by_artist.get(segments[1])
            if new_category is None:
                new_source_ids.append(source_id)
                continue
            segments[0] = new_category
            new_source_ids.append("/".join(segments))
        assert_safe_source_id_unique(new_source_ids)

        await session.execute(_text("SELECT pg_advisory_xact_lock(hashtext('jyzrox_local_category_migration'))"))

        for artist, (old_category, new_category) in sorted(moves.items()):
            params = {
                "root_prefix": root_prefix,
                "artist": artist,
                "old_category": old_category,
                "new_category": new_category,
            }
            for stmt in build_recategorize_sql_statements():
                result = await session.execute(_text(stmt.sql), params)
                print(f"  {artist:<28} {stmt.kind:<24} {result.rowcount:>7}")

        await session.commit()
    print("database committed")

    await _rebuild_library_tree(args)
    return 0


async def _rebuild_library_tree(args) -> None:
    """Recreate library symlinks, ownership markers and sidecars from the DB.

    Idempotent: it writes what should be there and then removes only dirs no
    gallery claims. ``create_library_symlink`` owns the marker and the
    relative-vs-absolute target rule, so neither is reimplemented here.
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from core.config import settings
    from core.database import AsyncSessionLocal
    from db.models import Gallery, Image
    from services.cas import create_library_symlink
    from services.library_sidecar import SIDECAR_FILENAME

    local_root = Path(settings.data_library_path) / "local"
    expected: set[str] = set()

    async with AsyncSessionLocal() as session:
        galleries = (
            (
                await session.execute(
                    select(Gallery)
                    .where(Gallery.source == "local")
                    .options(selectinload(Gallery.images).selectinload(Image.blob))
                    .order_by(Gallery.id)
                )
            )
            .scalars()
            .all()
        )
        for gallery in galleries:
            expected.add(safe_source_id(gallery.source_id))
            for image in gallery.images:
                if not image.filename or image.blob is None:
                    continue
                await create_library_symlink(
                    gallery.source,
                    gallery.source_id,
                    image.filename,
                    image.blob,
                    external_path=image.external_path,
                )
            # Drop the stale sidecar; reconciliation rewrites missing ones with
            # the new source_id and category.
            (local_root / safe_source_id(gallery.source_id) / SIDECAR_FILENAME).unlink(missing_ok=True)

    removed = prune_stale_library_dirs(local_root, expected, max_removals=args.max_stale)
    print(f"library tree rebuilt: {len(expected)} dirs kept, {len(removed)} stale dirs removed")


async def _cmd_verify(args) -> int:
    from sqlalchemy import text as _text

    from core.config import settings
    from core.database import AsyncSessionLocal

    root_prefix = args.root.rstrip("/") + "/"
    failures: list[str] = []

    async with AsyncSessionLocal() as session:
        total = (await session.execute(_text("SELECT count(*) FROM galleries WHERE source = 'local'"))).scalar_one()
        uncategorised = (
            await session.execute(
                _text("SELECT count(*) FROM galleries WHERE source = 'local' AND (category IS NULL OR category = '')")
            )
        ).scalar_one()
        wrong_segments = (
            await session.execute(
                _text(
                    "SELECT count(*) FROM galleries WHERE source = 'local' "
                    "AND array_length(string_to_array(source_id, '/'), 1) <> 4"
                )
            )
        ).scalar_one()
        rows = await session.execute(
            _text("SELECT external_path FROM images WHERE external_path LIKE :p"), {"p": root_prefix + "%"}
        )
        missing_files = sum(1 for (path,) in rows if not os.path.isfile(path))

    if uncategorised:
        failures.append(f"{uncategorised} local galleries still have no category")
    if wrong_segments:
        failures.append(f"{wrong_segments} local galleries do not have 4 source_id segments")
    if missing_files:
        failures.append(f"{missing_files} images point at a missing file")

    local_root = Path(settings.data_library_path) / "local"
    dangling = sum(
        1
        for gallery_dir in local_root.iterdir()
        if gallery_dir.is_dir()
        for link in gallery_dir.iterdir()
        if link.is_symlink() and not link.resolve().exists()
    )
    if dangling:
        failures.append(f"{dangling} dangling library symlinks")

    print(f"local galleries: {total}")
    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print("verify OK")
    return 0


async def _cmd_rebuild_tree(args) -> int:
    """Resume/repair the library tree from the DB's current state.

    Deliberately independent of ``--mapping``: after ``commit`` has already
    rewritten the database, ``artists`` in that table reflect the *new*
    category-prefixed values, so re-validating against the old artist->
    category mapping would either be a no-op or (worse) reject valid state.
    This only reconciles symlinks/markers/sidecars and prunes unclaimed dirs,
    which is safe to run against any DB state, including a normal library
    that was never touched by this migration.
    """
    await _rebuild_library_tree(args)
    return 0


def _cmd_move_source(args) -> int:
    mapping = load_mapping(args.mapping)
    _validate_category_names_only(mapping)
    moves = move_source_tree(args.root, mapping, reverse=args.reverse)
    for src, dst in moves:
        print(f"  {src}\n    -> {dst}")
    print(f"moved {len(moves)} artist directories ({'reverse' if args.reverse else 'forward'})")
    return 0


def _cmd_recategorize_source(args) -> int:
    mapping = load_mapping(args.mapping)
    _validate_category_names_only(mapping)
    moves = recategorize_source_tree(args.root, mapping)
    for src, dst in moves:
        print(f"  {src}\n    -> {dst}")
    print(f"recategorized {len(moves)} artist directories")
    return 0


def _validate_category_names_only(mapping: dict[str, str]) -> None:
    """move-source/recategorize-source have no DB access, so they validate
    names but not coverage."""
    validate_mapping(mapping, set(mapping))


# Subcommands that read the artist->category mapping and must not run
# without one. ``rebuild-tree`` and ``verify`` are DB-state-driven and
# deliberately excluded: see ``_cmd_rebuild_tree`` for why re-validating a
# stale mapping against a post-commit DB would be wrong, not just redundant.
_COMMANDS_REQUIRING_MAPPING = {
    "plan",
    "move-source",
    "commit",
    "recategorize-source",
    "recategorize-commit",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=[
            "plan",
            "move-source",
            "commit",
            "verify",
            "rebuild-tree",
            "recategorize-source",
            "recategorize-commit",
        ],
    )
    parser.add_argument(
        "--mapping",
        default=None,
        help="artist<TAB>category TSV (required for plan/move-source/commit/recategorize-source/recategorize-commit)",
    )
    parser.add_argument("--root", required=True, help="library root, e.g. /mnt/ssd-data/images")
    parser.add_argument("--pattern", default="{category}/{artist}/{_}/{title}")
    parser.add_argument("--reverse", action="store_true", help="move-source only: undo the move")
    parser.add_argument(
        "--max-stale",
        type=int,
        default=_MAX_STALE_LIBRARY_DIRS,
        help=(
            "commit/recategorize-commit/rebuild-tree only: max number of unclaimed library dirs the "
            f"tree rebuild may remove (default {_MAX_STALE_LIBRARY_DIRS}); raise this explicitly after "
            "confirming the extra dirs are safe, e.g. a rename-style migration where stale count is "
            "roughly gallery count + pre-existing orphans"
        ),
    )
    args = parser.parse_args(argv)

    try:
        if args.command in _COMMANDS_REQUIRING_MAPPING and not args.mapping:
            raise MigrationError(f"--mapping is required for {args.command}")
        if args.command == "move-source":
            return _cmd_move_source(args)
        if args.command == "recategorize-source":
            return _cmd_recategorize_source(args)
        import asyncio

        handlers = {
            "plan": _cmd_plan,
            "commit": _cmd_commit,
            "verify": _cmd_verify,
            "rebuild-tree": _cmd_rebuild_tree,
            "recategorize-commit": _cmd_recategorize_commit,
        }
        return asyncio.run(handlers[args.command](args))
    except MigrationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
