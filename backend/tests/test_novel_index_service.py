"""Tests for services.novel_index — pure derivation of the knowledge index.

Task 2 covers the pure (no-DB) builders; Task 4 adds the async persistence tests.
"""

from pathlib import Path

from services import novel_index


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
