"""Regression tests for schema hardening — edge cases #144 and #190.

These tests verify that db/init.sql contains the required indexes and constraints
added to prevent data-integrity and performance issues identified in the audit.
"""

from pathlib import Path

_INIT_SQL = Path(__file__).parent.parent.parent / "db" / "init.sql"


# ---------------------------------------------------------------------------
# edge case #144 — read_progress single-column lookup indexes
# ---------------------------------------------------------------------------


class TestReadProgressIndexes:
    """read_progress must define indexes for single-column user_id / gallery_id lookups — edge case #144.

    Before the fix, the only index on read_progress was the composite PRIMARY KEY
    (user_id, gallery_id), which forces a full table scan for queries on either
    column alone (e.g. "recent reads by user" or "recent reads of a gallery").
    """

    def test_init_sql_has_read_progress_user_index(self):
        content = _INIT_SQL.read_text()
        assert "idx_read_progress_user" in content, (
            "init.sql must define idx_read_progress_user for single-column user_id lookups"
        )

    def test_init_sql_has_read_progress_gallery_index(self):
        content = _INIT_SQL.read_text()
        assert "idx_read_progress_gallery" in content, (
            "init.sql must define idx_read_progress_gallery for single-column gallery_id lookups"
        )

    def test_read_progress_indexes_cover_last_read_at(self):
        content = _INIT_SQL.read_text()
        idx_block_start = content.find("idx_read_progress_user")
        idx_block = content[idx_block_start : idx_block_start + 300]
        assert "last_read_at" in idx_block, (
            "read_progress indexes should include last_read_at for recency-ordered queries"
        )


# ---------------------------------------------------------------------------
# edge case #190 — users.role CHECK constraint
# ---------------------------------------------------------------------------


class TestUsersRoleConstraint:
    """users.role must be constrained to known values via a CHECK constraint — edge case #190.

    Before the fix, users.role was a plain TEXT column with only a DEFAULT value.
    Any string could be written, silently breaking the role-hierarchy auth logic.
    """

    def test_init_sql_has_role_check_constraint(self):
        content = _INIT_SQL.read_text()
        assert "chk_users_role" in content, "init.sql must define chk_users_role CHECK constraint on users.role"

    def test_role_check_constraint_includes_admin(self):
        content = _INIT_SQL.read_text()
        constraint_block_start = content.find("chk_users_role")
        constraint_block = content[constraint_block_start : constraint_block_start + 120]
        assert "'admin'" in constraint_block

    def test_role_check_constraint_includes_member(self):
        content = _INIT_SQL.read_text()
        constraint_block_start = content.find("chk_users_role")
        constraint_block = content[constraint_block_start : constraint_block_start + 120]
        assert "'member'" in constraint_block

    def test_role_check_constraint_includes_viewer(self):
        content = _INIT_SQL.read_text()
        constraint_block_start = content.find("chk_users_role")
        constraint_block = content[constraint_block_start : constraint_block_start + 120]
        assert "'viewer'" in constraint_block

    def test_role_hierarchy_matches_db_constraint_values(self):
        """ROLE_HIERARCHY in core.auth must match the roles allowed by the DB constraint — edge case #190."""
        from core.auth import ROLE_HIERARCHY

        db_allowed = {"admin", "member", "viewer"}
        assert set(ROLE_HIERARCHY.keys()) == db_allowed, (
            "core.auth.ROLE_HIERARCHY and the DB chk_users_role constraint must allow identical role sets"
        )
