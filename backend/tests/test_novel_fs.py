import os
from pathlib import Path

import pytest

from services.novel_fs import (
    NovelPathError,
    file_exists,
    keyword_scan,
    list_chapters,
    list_works,
    parse_acts,
    parse_backlinks,
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
