"""Regression tests for scripts/migrate_local_category.py.

Only the pieces that are safe to exercise without a live Postgres: the
statement ordering contract imposed by the non-deferrable composite FK, the
source-tree rename (including its reverse), and the library-tree rebuild's
fail-closed guard.
"""

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "migrate_local_category.py"


@pytest.fixture
def mig():
    spec = importlib.util.spec_from_file_location("migrate_local_category", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestStatementOrder:
    def test_blob_locations_are_inserted_before_images_are_updated(self, mig):
        """fk_images_blob_location is NOT deferrable: rows must exist first."""
        statements = mig.build_sql_statements()
        kinds = [s.kind for s in statements]
        assert kinds.index("insert_blob_locations") < kinds.index("update_images")

    def test_old_blob_locations_are_deleted_after_images_are_updated(self, mig):
        statements = mig.build_sql_statements()
        kinds = [s.kind for s in statements]
        assert kinds.index("update_images") < kinds.index("delete_blob_locations")

    def test_every_statement_is_parameterised_on_the_library_root(self, mig):
        """No statement may rewrite paths outside the configured root."""
        for stmt in mig.build_sql_statements():
            assert ":root_prefix" in stmt.sql, stmt.kind


class TestMoveSource:
    def test_move_source_creates_category_dir_and_moves_artist(self, mig, tmp_path):
        (tmp_path / "abfluss" / "2025" / "g1").mkdir(parents=True)
        mig.move_source_tree(str(tmp_path), {"abfluss": "Artist CG"}, reverse=False)

        assert (tmp_path / "Artist CG" / "abfluss" / "2025" / "g1").is_dir()
        assert not (tmp_path / "abfluss").exists()

    def test_move_source_is_reversible(self, mig, tmp_path):
        (tmp_path / "abfluss" / "2025" / "g1").mkdir(parents=True)
        mapping = {"abfluss": "Artist CG"}
        mig.move_source_tree(str(tmp_path), mapping, reverse=False)
        mig.move_source_tree(str(tmp_path), mapping, reverse=True)

        assert (tmp_path / "abfluss" / "2025" / "g1").is_dir()
        assert not (tmp_path / "Artist CG").exists()

    def test_move_source_refuses_when_destination_already_exists(self, mig, tmp_path):
        (tmp_path / "abfluss").mkdir()
        (tmp_path / "Artist CG" / "abfluss").mkdir(parents=True)
        with pytest.raises(mig.MigrationError, match="already exists"):
            mig.move_source_tree(str(tmp_path), {"abfluss": "Artist CG"}, reverse=False)

    def test_move_source_refuses_when_artist_dir_is_missing(self, mig, tmp_path):
        with pytest.raises(mig.MigrationError, match="missing artist directory"):
            mig.move_source_tree(str(tmp_path), {"ghost": "Artist CG"}, reverse=False)


class TestPruneStaleLibraryDirs:
    def test_prune_removes_only_directories_absent_from_the_expected_set(self, mig, tmp_path):
        for name in ("keep_me", "stale_one"):
            (tmp_path / name).mkdir()
        removed = mig.prune_stale_library_dirs(tmp_path, {"keep_me"}, max_removals=10)

        assert removed == ["stale_one"]
        assert (tmp_path / "keep_me").is_dir()
        assert not (tmp_path / "stale_one").exists()

    def test_prune_fails_closed_on_empty_expected_set(self, mig, tmp_path):
        (tmp_path / "anything").mkdir()
        with pytest.raises(mig.MigrationError, match="expected set is empty"):
            mig.prune_stale_library_dirs(tmp_path, set(), max_removals=10)

    def test_prune_fails_closed_when_removal_count_exceeds_threshold(self, mig, tmp_path):
        (tmp_path / "keep").mkdir()
        for i in range(5):
            (tmp_path / f"stale{i}").mkdir()
        with pytest.raises(mig.MigrationError, match="refusing to remove"):
            mig.prune_stale_library_dirs(tmp_path, {"keep"}, max_removals=3)

    def test_prune_ignores_regular_files(self, mig, tmp_path):
        (tmp_path / "keep").mkdir()
        (tmp_path / "loose.txt").write_text("x", encoding="utf-8")
        assert mig.prune_stale_library_dirs(tmp_path, {"keep"}, max_removals=10) == []
        assert (tmp_path / "loose.txt").is_file()


# ---------------------------------------------------------------------------
# Round 2: recategorize — moving an artist between existing category dirs
# (build_sql_statements()/move_source_tree() insert a category segment for
# the first time; build_recategorize_sql_statements()/recategorize_source_tree()
# instead replace an already-present category segment.)
# ---------------------------------------------------------------------------


class TestRecategorizeStatementOrder:
    def test_kind_order_matches_build_sql_statements(self, mig):
        """The recategorize statements are the same 5 kinds, in the same
        order, as the original insert-a-category migration."""
        assert [s.kind for s in mig.build_recategorize_sql_statements()] == [s.kind for s in mig.build_sql_statements()]

    def test_blob_locations_are_inserted_before_images_are_updated(self, mig):
        """fk_images_blob_location is NOT deferrable: rows must exist first."""
        statements = mig.build_recategorize_sql_statements()
        kinds = [s.kind for s in statements]
        assert kinds.index("insert_blob_locations") < kinds.index("update_images")

    def test_old_blob_locations_are_deleted_after_images_are_updated(self, mig):
        statements = mig.build_recategorize_sql_statements()
        kinds = [s.kind for s in statements]
        assert kinds.index("update_images") < kinds.index("delete_blob_locations")

    def test_every_statement_is_parameterised_on_root_prefix_old_and_new_category(self, mig):
        for stmt in mig.build_recategorize_sql_statements():
            assert ":root_prefix" in stmt.sql, stmt.kind
            assert ":old_category" in stmt.sql, stmt.kind
            assert ":new_category" in stmt.sql, stmt.kind

    def test_every_statement_uses_starts_with_not_like(self, mig):
        """Round-1 regression guard: an artist name like 'Nai_奈緋'
        contains '_', which is a SQL LIKE wildcard. A LIKE-based WHERE clause
        silently over-matches other rows sharing the same prefix shape and
        would UPDATE/DELETE far more rows than intended (this bit the first
        round against ~90k rows). starts_with() treats '_' literally and
        must be used instead."""
        for stmt in mig.build_recategorize_sql_statements():
            assert "starts_with(" in stmt.sql, stmt.kind
            assert " LIKE " not in stmt.sql, stmt.kind


class TestRecategorizeSourceTree:
    def test_moves_artist_from_current_category_dir_to_target_category_dir(self, mig, tmp_path):
        (tmp_path / "Image Set" / "abfluss").mkdir(parents=True)
        moves = mig.recategorize_source_tree(str(tmp_path), {"abfluss": "Artist CG"})

        assert (tmp_path / "Artist CG" / "abfluss").is_dir()
        assert not (tmp_path / "Image Set" / "abfluss").exists()
        assert moves == [(str(tmp_path / "Image Set" / "abfluss"), str(tmp_path / "Artist CG" / "abfluss"))]

    def test_raises_when_artist_appears_under_multiple_category_dirs(self, mig, tmp_path):
        """Fail closed: if the artist directory exists under more than one
        category, which one is 'current' is ambiguous and must not be
        guessed."""
        (tmp_path / "Image Set" / "abfluss").mkdir(parents=True)
        (tmp_path / "Cosplay" / "abfluss").mkdir(parents=True)
        with pytest.raises(mig.MigrationError, match="ambiguous"):
            mig.recategorize_source_tree(str(tmp_path), {"abfluss": "Artist CG"})

    def test_raises_when_artist_is_not_found_under_any_category_dir(self, mig, tmp_path):
        (tmp_path / "Image Set").mkdir(parents=True)
        with pytest.raises(mig.MigrationError):
            mig.recategorize_source_tree(str(tmp_path), {"ghost": "Artist CG"})

    def test_raises_and_does_not_overwrite_when_destination_already_exists(self, mig, tmp_path):
        (tmp_path / "Image Set" / "abfluss").mkdir(parents=True)
        (tmp_path / "Image Set" / "abfluss" / "keep.txt").write_text("source marker", encoding="utf-8")
        dest = tmp_path / "Artist CG" / "abfluss"
        dest.mkdir(parents=True)
        (dest / "existing.txt").write_text("dest marker", encoding="utf-8")

        with pytest.raises(mig.MigrationError, match="already exists"):
            mig.recategorize_source_tree(str(tmp_path), {"abfluss": "Artist CG"})

        # Neither side may be touched by the refused move.
        assert (dest / "existing.txt").read_text(encoding="utf-8") == "dest marker"
        assert not (dest / "keep.txt").exists()
        assert (tmp_path / "Image Set" / "abfluss" / "keep.txt").is_file()

    def test_skips_artist_already_in_its_target_category_and_produces_no_move(self, mig, tmp_path):
        (tmp_path / "Artist CG" / "abfluss").mkdir(parents=True)
        moves = mig.recategorize_source_tree(str(tmp_path), {"abfluss": "Artist CG"})

        assert moves == []
        assert (tmp_path / "Artist CG" / "abfluss").is_dir()

    def test_removes_emptied_source_category_dir_after_move(self, mig, tmp_path):
        (tmp_path / "Image Set" / "abfluss").mkdir(parents=True)
        mig.recategorize_source_tree(str(tmp_path), {"abfluss": "Artist CG"})

        assert not (tmp_path / "Image Set").exists()

    def test_does_not_remove_source_category_dir_when_a_sibling_artist_remains(self, mig, tmp_path):
        (tmp_path / "Image Set" / "abfluss").mkdir(parents=True)
        (tmp_path / "Image Set" / "omochi").mkdir(parents=True)
        mig.recategorize_source_tree(str(tmp_path), {"abfluss": "Artist CG"})

        assert (tmp_path / "Image Set").is_dir()
        assert (tmp_path / "Image Set" / "omochi").is_dir()
