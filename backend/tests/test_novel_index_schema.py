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
