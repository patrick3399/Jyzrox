"""Tests for services.novel_index — pure derivation of the knowledge index."""

from pathlib import Path

import pytest

from services import novel_index
from services.novel_index import scan_mentions


def _repo(tmp_path: Path) -> Path:
    w = tmp_path / "作品A"
    (w / "Setting").mkdir(parents=True)
    (w / "Setting" / "設定-張三.md").write_text(
        "---\ntype: character\naliases: [小三]\n---\n# 張三\n設定內容", encoding="utf-8"
    )
    (w / "01.md").write_text("張三走進房間。小三笑了。\n李四也在。", encoding="utf-8")
    (w / "02.md").write_text("只有張三。", encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize(
    ("stem", "expected"),
    [
        ("設定-甲v1", ("甲", 1)),
        ("設定-甲v12", ("甲", 12)),
        ("設定-甲", ("甲", 0)),
        ("設定-甲v2機甲", ("甲v2機甲", 0)),
        ("參考-甲", None),
        ("setting-v1", None),
    ],
)
def test_entity_of_reads_name_and_version_from_the_stem(stem, expected):
    assert novel_index.entity_of(stem) == expected


def test_build_note_records_reads_frontmatter(tmp_path):
    recs = novel_index.build_note_records(_repo(tmp_path))
    assert len(recs) == 1
    r = recs[0]
    assert r["file_path"] == "作品A/Setting/設定-張三.md"
    assert r["work"] == "作品A"
    assert r["title"] == "張三" and r["note_type"] == "character"
    assert r["aliases"] == ["張三", "小三"]
    assert r["frontmatter"]["type"] == "character"


def test_scan_mentions_counts_name_and_alias(tmp_path):
    ms = novel_index.scan_mentions(_repo(tmp_path))
    by_ch = {m["chapter_path"]: m for m in ms if m["note_path"].endswith("設定-張三.md")}
    assert by_ch["作品A/01.md"]["mention_count"] == 2  # 張三 + 小三
    assert by_ch["作品A/01.md"]["first_offset"] == 0
    assert by_ch["作品A/02.md"]["mention_count"] == 1


def test_mentions_go_to_the_highest_setting_version_not_to_reference_notes(tmp_path):
    """The first note in path order used to win every alias, and `參考-` sorts
    before `設定-`, so a reference note took 77% of the real corpus's mentions
    while 8 of 10 canonical notes got none."""
    s = tmp_path / "作品A" / "Setting"
    s.mkdir(parents=True)
    (s / "參考-甲-乙.md").write_text("# 參考\n", encoding="utf-8")
    (s / "設定-甲v1.md").write_text("# 甲 舊版\n", encoding="utf-8")
    (s / "設定-甲v2.md").write_text("# 甲\n", encoding="utf-8")
    (tmp_path / "作品A" / "01.md").write_text("甲來了，乙也來了。", encoding="utf-8")
    ms = scan_mentions(tmp_path)
    assert [(m["note_path"], m["mention_count"]) for m in ms] == [("作品A/Setting/設定-甲v2.md", 1)]
    aliases = {r["file_path"]: r["aliases"] for r in novel_index.build_note_records(tmp_path)}
    assert aliases["作品A/Setting/設定-甲v1.md"] == []  # superseded version
    assert "作品A/Setting/參考-甲-乙.md" not in aliases  # not an entity note


def test_mentions_do_not_cross_into_another_work(tmp_path):
    """Entity names were matched globally: one work's character note collected
    mentions from every other work that used the same name."""
    (tmp_path / "作品A" / "Setting").mkdir(parents=True)
    (tmp_path / "作品A" / "Setting" / "設定-甲.md").write_text("# 甲\n", encoding="utf-8")
    (tmp_path / "作品A" / "01.md").write_text("甲。", encoding="utf-8")
    (tmp_path / "作品B").mkdir()
    (tmp_path / "作品B" / "01.md").write_text("甲也在這裡。", encoding="utf-8")
    assert {m["chapter_path"] for m in scan_mentions(tmp_path)} == {"作品A/01.md"}


def test_world_setting_doc_is_scanned_only_for_explicit_aliases(tmp_path):
    """`setting.md` has no entity name in its filename; deriving one produced
    the alias 'setting', which matched nothing useful."""
    w = tmp_path / "作品A"
    (w / "Setting").mkdir(parents=True)
    (w / "setting.md").write_text("# 世界觀\n", encoding="utf-8")
    (w / "Setting" / "setting-v1.md").write_text("---\naliases: [裝甲]\n---\n# 裝甲設定\n", encoding="utf-8")
    (w / "01.md").write_text("setting 世界觀 裝甲", encoding="utf-8")
    ms = scan_mentions(tmp_path)
    assert [(m["note_path"], m["mention_count"]) for m in ms] == [("作品A/Setting/setting-v1.md", 1)]


def test_scan_mentions_excludes_old_dir_duplicate_chapters(tmp_path):
    w = tmp_path / "作品B"
    (w / "Old").mkdir(parents=True)
    (w / "Setting").mkdir()
    (w / "01.md").write_text("張三登場。\n", encoding="utf-8")
    (w / "Old" / "01.md").write_text("張三登場。\n", encoding="utf-8")
    (w / "Setting" / "設定-張三v1.md").write_text("# 張三\n", encoding="utf-8")
    chapter_paths = {m["chapter_path"] for m in scan_mentions(tmp_path)}
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
    assert d["張三"]["dst_path"] == "作品A/Setting/設定-張三.md"
    assert d["不存在的人"]["dst_path"] is None


def test_corpus_health_flags_drift_from_the_conventions(tmp_path):
    """The 2026-08 reorganisation moved files where no rule expected them and
    nothing noticed for two months; the health report is that signal."""
    w = tmp_path / "作品A"
    (w / "Setting").mkdir(parents=True)
    (w / "01.md").write_text("第1章：開場\n\n甲。\n\n（第1章 完）\n", encoding="utf-8")
    (w / "02.md").write_text("### 第二章：x\n\n（第2章 完）\n", encoding="utf-8")
    (w / "番外短篇.md").write_text("x", encoding="utf-8")
    (w / "FORMAT.md").write_text("# 格式\n", encoding="utf-8")
    (w / "Setting" / "設定-甲.md").write_text("# 甲\n", encoding="utf-8")
    (w / "Setting" / "設定-乙.md").write_text("# 乙\n", encoding="utf-8")
    notes = novel_index.build_note_records(tmp_path)
    health = novel_index.corpus_health(tmp_path, notes, novel_index.scan_mentions(tmp_path))
    assert health == {
        "stray_root_files": ["作品A/番外短篇.md"],
        "chapters_with_format_issues": 1,
        "entities_without_mentions": ["作品A/Setting/設定-乙.md"],
    }


# ── Task 4: async persistence (full rebuild) ──


async def test_reindex_all_populates_and_is_idempotent(tmp_path, db_session):
    from sqlalchemy import func as safunc
    from sqlalchemy import select

    from db.models import NovelMention, NovelNote

    _repo(tmp_path)
    r1 = await novel_index.reindex_all(db_session, tmp_path)
    assert r1["notes"] == 1 and r1["mentions"] >= 2
    assert set(r1["health"]) == {"stray_root_files", "chapters_with_format_issues", "entities_without_mentions"}

    n = (await db_session.execute(select(safunc.count()).select_from(NovelNote))).scalar()
    assert n == 1
    note = (await db_session.execute(select(NovelNote))).scalars().first()
    assert note.aliases == ["張三", "小三"]  # round-trips as a Python list
    assert note.frontmatter["type"] == "character"

    r2 = await novel_index.reindex_all(db_session, tmp_path)
    assert r2 == r1  # deterministic rebuild
    m = (await db_session.execute(select(safunc.count()).select_from(NovelMention))).scalar()
    assert m == r1["mentions"]
