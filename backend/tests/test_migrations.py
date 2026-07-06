"""Regression test: alembic migration revision ids must form one linear chain.

A duplicate `revision` id across two files (each still pointing at the same
`down_revision`) is not rejected at edit time — it only surfaces the moment
something walks the graph (``alembic history``, ``alembic upgrade head``,
i.e. the `migrate` container on deploy), where it raises
``CommandError: Requested revision X overlaps with other requested revisions Y``.
"""

import os

from alembic.config import Config
from alembic.script import ScriptDirectory

_BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..")


def _script_directory() -> ScriptDirectory:
    cfg = Config()
    cfg.set_main_option("script_location", os.path.join(_BACKEND_DIR, "migrations"))
    return ScriptDirectory.from_config(cfg)


def test_migration_revisions_are_unique_and_linear():
    script = _script_directory()

    revisions = list(script.walk_revisions())
    revision_ids = [r.revision for r in revisions]

    assert len(revision_ids) == len(set(revision_ids)), (
        f"duplicate revision id in backend/migrations/versions: {revision_ids}"
    )
    assert len(script.get_heads()) == 1, "migration graph has diverged into multiple heads"
