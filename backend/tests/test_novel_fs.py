import os
import re
from pathlib import Path

import pytest

from services.novel_fs import (
    NovelPathError,
    classify_path,
    count_work_files,
    file_exists,
    keyword_scan,
    list_chapters,
    list_notes,
    list_work_files,
    list_works,
    parse_acts,
    parse_backlinks,
    parse_frontmatter,
    read_file,
    safe_repo_path,
    set_frontmatter_value,
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
    # Real characters, not bytes: CJK prose is ~3 bytes each, so the byte size
    # used to overstate every chapter threefold.
    assert chapters[0]["chars"] == len(re.sub(r"\s+", "", _SAMPLE))
    assert chapters[0]["summary"] is None


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


def test_list_notes_includes_work_root_setting_md(tmp_path):
    root = _polluted_repo(tmp_path)
    notes = {n["path"]: n for n in list_notes(root)}
    assert "作品B/setting.md" in notes
    assert notes["作品B/setting.md"]["title"] == "世界觀"
    assert notes["作品B/setting.md"]["work"] == "作品B"
    assert "作品B/Setting/設定-1號-張三v1.md" in notes


def test_list_work_files_returns_category_subtree(tmp_path):
    root = _polluted_repo(tmp_path)
    scraps = list_work_files(root, "作品B", "scrap")
    assert [f["path"] for f in scraps] == ["作品B/Old/01.md"]
    assert scraps[0]["category"] == "scrap"
    drafts = list_work_files(root, "作品B", "draft")
    assert [f["path"] for f in drafts] == ["作品B/DEMO/demo1.md"]


def test_count_work_files_per_category(tmp_path):
    root = _polluted_repo(tmp_path)
    counts = count_work_files(root, "作品B")
    assert counts == {"extra": 0, "draft": 1, "reference": 1, "scrap": 1}


def test_keyword_scan_hits_carry_category(tmp_path):
    root = _polluted_repo(tmp_path)
    hits = keyword_scan(root, "張三")
    cats = {h["path"]: h["category"] for h in hits}
    assert cats["作品B/01.md"] == "main"
    assert cats["作品B/Old/01.md"] == "scrap"


# ── Chapter stats + summary (Phase 1.7) ────────────────────────────────────


def test_list_chapters_excludes_frontmatter_from_the_char_count(tmp_path):
    """Metadata is not prose: a chapter's count must not move when a summary is
    added, or the number stops matching what the author counts on the desktop."""
    (tmp_path / "作品A").mkdir()
    body = "# 第一章\n\n正文兩百字。\n"
    plain = tmp_path / "作品A" / "第01章.md"
    plain.write_text(body, encoding="utf-8")
    bare_count = list_chapters(tmp_path, "作品A")[0]["chars"]
    plain.write_text("---\nsummary: 這一章張三離開了城市\n---\n\n" + body, encoding="utf-8")
    ch = list_chapters(tmp_path, "作品A")[0]
    assert ch["chars"] == bare_count
    assert ch["summary"] == "這一章張三離開了城市"


def test_list_work_files_carries_chars_and_summary(tmp_path):
    (tmp_path / "作品A" / "草稿").mkdir(parents=True)
    (tmp_path / "作品A" / "草稿" / "試寫.md").write_text("---\nsummary: 一段試寫\n---\n\n草稿內容\n", encoding="utf-8")
    drafts = list_work_files(tmp_path, "作品A", "draft")
    assert drafts[0]["summary"] == "一段試寫"
    assert drafts[0]["chars"] == len("草稿內容")


def test_list_chapters_blank_summary_reads_as_absent(tmp_path):
    (tmp_path / "作品A").mkdir()
    (tmp_path / "作品A" / "第01章.md").write_text("---\nsummary: '  '\n---\n\n正文\n", encoding="utf-8")
    assert list_chapters(tmp_path, "作品A")[0]["summary"] is None


def test_set_frontmatter_value_adds_fence_to_a_plain_chapter():
    out = set_frontmatter_value("# 第一章\n\n正文\n", "summary", "張三離開")
    assert out == "---\nsummary: 張三離開\n---\n\n# 第一章\n\n正文\n"
    assert parse_frontmatter(out)[0]["summary"] == "張三離開"


def test_set_frontmatter_value_replaces_only_its_own_line():
    """Hand-written frontmatter is also edited on the desktop — every other key,
    its order and its exact formatting must survive untouched."""
    src = "---\ntype: character\naliases: [小三]   # 別名\nsummary: 舊摘要\n---\n\n# 張三\n內文\n"
    out = set_frontmatter_value(src, "summary", "新摘要")
    assert "aliases: [小三]   # 別名" in out
    assert out.index("type: character") < out.index("aliases:")
    assert parse_frontmatter(out)[0]["summary"] == "新摘要"
    assert out.endswith("---\n\n# 張三\n內文\n")


def test_set_frontmatter_value_quotes_a_summary_that_would_break_yaml():
    out = set_frontmatter_value("正文\n", "summary", "他說：「好」 #1: 開場")
    assert parse_frontmatter(out)[0]["summary"] == "他說：「好」 #1: 開場"


def test_set_frontmatter_value_collapses_newlines_into_one_line():
    """A multi-line value would break the line-oriented upsert (and the fence)."""
    out = set_frontmatter_value("正文\n", "summary", "第一行\n第二行")
    assert out.count("\n---\n") == 1
    assert parse_frontmatter(out)[0]["summary"] == "第一行 第二行"


def test_set_frontmatter_value_empty_removes_the_key_and_the_lone_fence():
    src = "# 第一章\n\n正文\n"
    with_summary = set_frontmatter_value(src, "summary", "摘要")
    assert set_frontmatter_value(with_summary, "summary", "") == src


def test_set_frontmatter_value_empty_keeps_a_fence_with_other_keys():
    src = "---\ntype: character\nsummary: 摘要\n---\n\n內文\n"
    out = set_frontmatter_value(src, "summary", "")
    assert out == "---\ntype: character\n---\n\n內文\n"


def test_set_frontmatter_value_empty_on_a_plain_file_is_a_noop():
    assert set_frontmatter_value("正文\n", "summary", "") == "正文\n"
