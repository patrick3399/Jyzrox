import os
from pathlib import Path

import pytest

from services.novel_fs import NovelPathError, safe_repo_path


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
