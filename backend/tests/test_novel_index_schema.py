"""Schema regression for the novel knowledge-index tables (BE-T15 triple-write).

Guards the primary keys the index persistence + queries rely on.
"""

from db.models import NovelLink, NovelMention, NovelNote


def test_models_have_expected_tables():
    assert NovelNote.__tablename__ == "novel_notes"
    assert NovelLink.__tablename__ == "novel_links"
    assert NovelMention.__tablename__ == "novel_mentions"


def test_primary_keys_match_spec():
    assert {c.name for c in NovelNote.__table__.primary_key} == {"file_path"}
    assert {c.name for c in NovelLink.__table__.primary_key} == {"src_path", "dst_title"}
    assert {c.name for c in NovelMention.__table__.primary_key} == {"note_path", "chapter_path"}


def test_migration_0005_statements_are_single_command():
    """asyncpg rejects multiple commands in one prepared statement — every
    op.execute in 0005 must carry exactly one SQL command (regression: the DDL
    was originally one multi-statement string and failed at deploy time)."""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).parent.parent / "migrations" / "versions" / "0005_novel_knowledge_index.py"
    spec = importlib.util.spec_from_file_location("mig0005", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for stmt in [*mod._UPGRADE_STATEMENTS, *mod._DOWNGRADE_STATEMENTS]:
        assert stmt.strip().rstrip(";").count(";") == 0, f"multi-command statement: {stmt!r}"
