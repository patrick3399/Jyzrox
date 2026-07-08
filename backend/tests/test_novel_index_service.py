"""Tests for services.novel_index — pure derivation of the knowledge index.

Task 2 covers the pure (no-DB) builders; Task 4 adds the async persistence tests.
"""

from pathlib import Path

from services import novel_index
from services.novel_index import scan_mentions


def _repo(tmp_path: Path) -> Path:
    w = tmp_path / "作品A"
    (w / "Setting").mkdir(parents=True)
    (w / "Setting" / "角色-張三.md").write_text(
        "---\ntype: character\naliases: [小三]\n---\n# 張三\n設定內容", encoding="utf-8"
    )
    (w / "01.md").write_text("張三走進房間。小三笑了。\n李四也在。", encoding="utf-8")
    (w / "02.md").write_text("只有張三。", encoding="utf-8")
    return tmp_path


def test_note_aliases_dedupes_title_and_aliases():
    assert novel_index.note_aliases({"aliases": ["小三", "張三"]}, "張三") == ["張三", "小三"]


def test_note_aliases_tolerates_missing_aliases():
    assert novel_index.note_aliases({}, "李四") == ["李四"]


def test_stem_aliases_extracts_names_from_structural_filenames():
    # Real repo convention: <type>-<N號>-<name><version> / 參考-<names>
    assert novel_index.stem_aliases("設定-1號-菈烏瑪v1") == ["菈烏瑪"]
    assert novel_index.stem_aliases("設定-4號-哥倫比婭v2") == ["哥倫比婭"]
    assert novel_index.stem_aliases("參考-多托雷-阿蕾奇諾-菈烏瑪") == ["多托雷", "阿蕾奇諾", "菈烏瑪"]
    assert novel_index.stem_aliases("參考-菈烏瑪v2-1") == ["菈烏瑪"]


def test_note_aliases_includes_stem_derived_names():
    result = novel_index.note_aliases({}, "設定-1號-菈烏瑪v1", stem="設定-1號-菈烏瑪v1")
    assert "菈烏瑪" in result


def test_build_note_records_reads_frontmatter(tmp_path):
    recs = novel_index.build_note_records(_repo(tmp_path))
    assert len(recs) == 1
    r = recs[0]
    assert r["file_path"] == "作品A/Setting/角色-張三.md"
    assert r["title"] == "張三" and r["note_type"] == "character"
    assert r["aliases"] == ["張三", "小三"]
    assert r["frontmatter"]["type"] == "character"


def test_scan_mentions_counts_title_and_alias(tmp_path):
    ms = novel_index.scan_mentions(_repo(tmp_path))
    by_ch = {m["chapter_path"]: m for m in ms if m["note_path"].endswith("角色-張三.md")}
    assert by_ch["作品A/01.md"]["mention_count"] == 2  # 張三 + 小三
    assert by_ch["作品A/01.md"]["first_offset"] == 0
    assert by_ch["作品A/02.md"]["mention_count"] == 1


def test_scan_mentions_excludes_old_dir_duplicate_chapters(tmp_path):
    w = tmp_path / "作品B"
    (w / "Old").mkdir(parents=True)
    (w / "Setting").mkdir()
    (w / "01.md").write_text("張三登場。\n", encoding="utf-8")
    (w / "Old" / "01.md").write_text("張三登場。\n", encoding="utf-8")
    (w / "Setting" / "設定-1號-張三v1.md").write_text("# 張三\n", encoding="utf-8")
    mentions = scan_mentions(tmp_path)
    chapter_paths = {m["chapter_path"] for m in mentions}
    assert "作品B/01.md" in chapter_paths
    assert "作品B/Old/01.md" not in chapter_paths


def test_scan_mentions_empty_when_no_notes(tmp_path):
    (tmp_path / "作品A").mkdir()
    (tmp_path / "作品A" / "01.md").write_text("沒有設定筆記的正文", encoding="utf-8")
    assert novel_index.scan_mentions(tmp_path) == []


def test_build_link_records_marks_broken(tmp_path):
    r = _repo(tmp_path)
    (r / "作品A" / "03.md").write_text("見 [[張三]] 與 [[不存在的人]]", encoding="utf-8")
    links = novel_index.build_link_records(r)
    d = {link["dst_title"]: link for link in links}
    assert d["張三"]["dst_path"] == "作品A/Setting/角色-張三.md"
    assert d["不存在的人"]["dst_path"] is None


# ── Task 4: async persistence (full rebuild) ──


async def test_reindex_all_populates_and_is_idempotent(tmp_path, db_session):
    from sqlalchemy import func as safunc
    from sqlalchemy import select

    from db.models import NovelMention, NovelNote

    _repo(tmp_path)
    r1 = await novel_index.reindex_all(db_session, tmp_path)
    assert r1["notes"] == 1 and r1["mentions"] >= 2

    n = (await db_session.execute(select(safunc.count()).select_from(NovelNote))).scalar()
    assert n == 1
    note = (await db_session.execute(select(NovelNote))).scalars().first()
    assert note.aliases == ["張三", "小三"]  # round-trips as a Python list
    assert note.frontmatter["type"] == "character"

    r2 = await novel_index.reindex_all(db_session, tmp_path)
    assert r2 == r1  # deterministic rebuild
    m = (await db_session.execute(select(safunc.count()).select_from(NovelMention))).scalar()
    assert m == r1["mentions"]
