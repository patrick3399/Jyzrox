import os
from pathlib import Path

import pytest

from services.novel_fs import (
    NovelPathError,
    classify_path,
    file_exists,
    keyword_scan,
    list_chapters,
    list_notes,
    list_works,
    parse_acts,
    parse_backlinks,
    parse_frontmatter,
    read_file,
    safe_repo_path,
    write_file,
)

_SAMPLE = "# 第一章\n\n### 幕一\n\n正文 [[張三]] 與 [[李四]]。\n\n### 幕二\n\n更多 [[張三]]。\n"


def _repo(tmp_path: Path) -> Path:
    (tmp_path / "作品A").mkdir()
    (tmp_path / "作品A" / "第01章.md").write_text("hello", encoding="utf-8")
    return tmp_path


def test_safe_repo_path_accepts_md_inside_root(tmp_path):
    root = _repo(tmp_path)
    p = safe_repo_path(root, "作品A/第01章.md")
    assert p == (root / "作品A" / "第01章.md").resolve()


@pytest.mark.parametrize(
    "bad",
    [
        "../etc/passwd",
        "作品A/../../secret.md",
        "/etc/passwd",
        "作品A/第01章.txt",  # non-.md
        "作品A/第01章",  # no extension
        "",  # empty
    ],
)
def test_safe_repo_path_rejects_unsafe(tmp_path, bad):
    root = _repo(tmp_path)
    with pytest.raises(NovelPathError):
        safe_repo_path(root, bad)


def test_safe_repo_path_rejects_symlink_escape(tmp_path):
    root = _repo(tmp_path)
    outside = tmp_path.parent / "outside.md"
    outside.write_text("x", encoding="utf-8")
    link = root / "作品A" / "link.md"
    os.symlink(outside, link)
    with pytest.raises(NovelPathError):
        safe_repo_path(root, "作品A/link.md")


def test_list_works_and_chapters(tmp_path):
    (tmp_path / "作品A").mkdir()
    (tmp_path / "作品A" / "第01章.md").write_text(_SAMPLE, encoding="utf-8")
    (tmp_path / "設定").mkdir()  # excluded from works
    works = list_works(tmp_path)
    assert works == [{"name": "作品A", "chapter_count": 1}]
    chapters = list_chapters(tmp_path, "作品A")
    assert chapters[0]["path"] == "作品A/第01章.md"
    assert chapters[0]["chars"] == len(_SAMPLE.encode("utf-8"))


def test_parse_acts(tmp_path):
    acts = parse_acts(_SAMPLE)
    assert [a["title"] for a in acts] == ["幕一", "幕二"]
    assert acts[0]["index"] == 0


def test_parse_backlinks_distinct_in_order(tmp_path):
    assert parse_backlinks(_SAMPLE) == ["張三", "李四"]


def test_write_then_read_roundtrip(tmp_path):
    (tmp_path / "作品A").mkdir()
    write_file(tmp_path, "作品A/新.md", "內容")
    assert read_file(tmp_path, "作品A/新.md") == "內容"


def test_file_exists_true_for_existing_md(tmp_path):
    root = _repo(tmp_path)
    assert file_exists(root, "作品A/第01章.md") is True


def test_file_exists_false_for_missing_md(tmp_path):
    root = _repo(tmp_path)
    assert file_exists(root, "作品A/第99章.md") is False


def test_file_exists_rejects_traversal(tmp_path):
    """An escaping path must raise, not report False (which would let a create clobber it)."""
    root = _repo(tmp_path)
    with pytest.raises(NovelPathError):
        file_exists(root, "../secret.md")


def test_keyword_scan_returns_path_line_context(tmp_path):
    (tmp_path / "作品A").mkdir()
    (tmp_path / "作品A" / "第01章.md").write_text(_SAMPLE, encoding="utf-8")
    hits = keyword_scan(tmp_path, "李四")
    assert hits and hits[0]["path"] == "作品A/第01章.md"
    assert "李四" in hits[0]["text"]


def test_keyword_scan_skips_dot_directories(tmp_path):
    """Search must not leak repo-internal files under a dot-dir (e.g. .git)."""
    (tmp_path / "作品A").mkdir()
    (tmp_path / "作品A" / "第01章.md").write_text("正文 keyword", encoding="utf-8")
    gitdir = tmp_path / ".git"
    gitdir.mkdir()
    (gitdir / "leak.md").write_text("keyword in git internals", encoding="utf-8")
    hits = keyword_scan(tmp_path, "keyword")
    assert any(h["path"] == "作品A/第01章.md" for h in hits)
    assert all(not h["path"].startswith(".git") for h in hits)


def test_safe_repo_path_rejects_null_byte(tmp_path):
    """A null byte must surface as NovelPathError (400), not a bare ValueError (500)."""
    root = _repo(tmp_path)
    with pytest.raises(NovelPathError):
        safe_repo_path(root, "作品A/\x00.md")


def test_list_chapters_rejects_null_byte(tmp_path):
    root = _repo(tmp_path)
    with pytest.raises(NovelPathError):
        list_chapters(root, "作品A\x00")


# ── Knowledge-index adaptation (Phase 1 Track A): Setting notes vs chapters ──


def test_list_chapters_excludes_setting_dir(tmp_path):
    w = tmp_path / "作品A"
    (w / "Setting").mkdir(parents=True)
    (w / "01.md").write_text("x", encoding="utf-8")
    (w / "Setting" / "角色-張三.md").write_text("# 張三\n", encoding="utf-8")
    chapters = list_chapters(tmp_path, "作品A")
    assert [c["path"] for c in chapters] == ["作品A/01.md"]


def test_list_notes_finds_setting_notes_with_title(tmp_path):
    w = tmp_path / "作品A"
    (w / "Setting").mkdir(parents=True)
    (w / "Setting" / "角色-張三.md").write_text("# 張三\n\n內容", encoding="utf-8")
    notes = list_notes(tmp_path)
    assert notes == [{"path": "作品A/Setting/角色-張三.md", "work": "作品A", "title": "張三"}]


def test_list_notes_title_falls_back_to_stem(tmp_path):
    w = tmp_path / "作品A"
    (w / "Setting").mkdir(parents=True)
    (w / "Setting" / "地點-王城.md").write_text("no heading here", encoding="utf-8")
    assert list_notes(tmp_path)[0]["title"] == "地點-王城"


def test_parse_frontmatter_none_returns_empty():
    assert parse_frontmatter("# Title\nbody") == ({}, "# Title\nbody")


def test_parse_frontmatter_valid():
    fm, body = parse_frontmatter("---\ntype: character\naliases: [小三]\n---\n# 張三\n")
    assert fm["type"] == "character" and fm["aliases"] == ["小三"]
    assert body.strip() == "# 張三"


def test_parse_frontmatter_malformed_does_not_raise():
    fm, body = parse_frontmatter("---\n: : bad yaml : :\n---\nbody")
    assert fm == {} and "body" in body


def _polluted_repo(tmp_path: Path) -> Path:
    """Mimics the real corpus: legacy Old/DEMO/extend dirs + special root files."""
    w = tmp_path / "作品B"
    (w / "Old").mkdir(parents=True)
    (w / "DEMO").mkdir()
    (w / "Setting").mkdir()
    (w / "01.md").write_text("# 第一章\n\n張三登場。\n", encoding="utf-8")
    (w / "02.md").write_text("", encoding="utf-8")  # 0-byte placeholder
    (w / "setting.md").write_text("# 世界觀\n", encoding="utf-8")
    (w / "FORMAT.md").write_text("# 格式\n", encoding="utf-8")
    (w / "Old" / "01.md").write_text("# 舊版\n\n張三登場。\n", encoding="utf-8")
    (w / "DEMO" / "demo1.md").write_text("# 試寫\n", encoding="utf-8")
    (w / "Setting" / "設定-1號-張三v1.md").write_text("# 張三\n", encoding="utf-8")
    return tmp_path


def test_list_chapters_returns_only_main_not_legacy_or_special_files(tmp_path):
    root = _polluted_repo(tmp_path)
    paths = [c["path"] for c in list_chapters(root, "作品B")]
    assert paths == ["作品B/01.md", "作品B/02.md"]
    assert all(c["category"] == "main" for c in list_chapters(root, "作品B"))


def test_list_works_chapter_count_excludes_legacy_and_special_files(tmp_path):
    root = _polluted_repo(tmp_path)
    works = {w["name"]: w["chapter_count"] for w in list_works(root)}
    assert works["作品B"] == 2


@pytest.mark.parametrize(
    ("rel", "expected"),
    [
        # main = first-level file directly under the work dir
        ("作品A/01.md", "main"),
        ("作品A/第01章.md", "main"),
        # special root files
        ("作品A/setting.md", "setting"),
        ("作品A/Setting.md", "setting"),  # case-insensitive
        ("作品A/FORMAT.md", "reference"),
        ("作品A/format.md", "reference"),
        # standard category dirs
        ("作品A/Setting/設定-1號-角色v1.md", "setting"),
        ("作品A/設定/角色.md", "setting"),
        ("作品A/參考/大綱.md", "reference"),
        ("作品A/草稿/03alt.md", "draft"),
        ("作品A/廢案/03.md", "scrap"),
        ("作品A/番外/短篇.md", "extra"),
        # legacy aliases (read-only compatibility), case-insensitive
        ("流螢 - 熔火之繭/Old/01.md", "scrap"),
        ("流螢 - 熔火之繭/old/01.md", "scrap"),
        ("璃月 - 等價交換/DEMO/demo1.md", "draft"),
        ("惡靈古堡 - 赤紅深淵/extend/01n.md", "draft"),
        # unknown subdir → reference, never silently main
        ("作品A/notes/random.md", "reference"),
        # nested subtree inherits the category
        ("作品A/廢案/v1/03.md", "scrap"),
        ("作品A/Setting/deep/角色.md", "setting"),
        # repo-root file (FORMAT.md, AGENTS.md at repo root) → reference
        ("FORMAT.md", "reference"),
    ],
)
def test_classify_path(rel, expected):
    assert classify_path(rel) == expected
