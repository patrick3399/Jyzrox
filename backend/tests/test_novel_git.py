import subprocess
from pathlib import Path

import pytest

from services import novel_git


def _run(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture()
def repos(tmp_path):
    """A bare 'origin' + one working clone, both real git."""
    bare = tmp_path / "origin.git"
    bare.mkdir()
    _run(bare, "init", "--bare", "-b", "main")
    work = tmp_path / "work"
    _run(tmp_path, "clone", str(bare), str(work))
    _run(work, "config", "user.email", "jyzrox@local")
    _run(work, "config", "user.name", "Jyzrox")
    (work / "作品A").mkdir()
    (work / "作品A" / "第01章.md").write_text("v1\n", encoding="utf-8")
    _run(work, "add", ".")
    _run(work, "commit", "-m", "init")
    _run(work, "push", "origin", "main")
    return {"bare": bare, "work": work}


async def test_commit_and_push_produces_commit(repos):
    work = str(repos["work"])
    (Path(work) / "作品A" / "第01章.md").write_text("v2\n", encoding="utf-8")
    result = await novel_git.commit_and_push(work, "作品A/第01章.md", "edit: 作品A/第01章.md")
    assert result["pushed"] is True
    log = await novel_git.log_file(work, "作品A/第01章.md")
    assert log[0]["message"] == "edit: 作品A/第01章.md"


async def test_status_reports_clean_head(repos):
    st = await novel_git.status(str(repos["work"]))
    assert st["clean"] is True and st["locked"] is False and len(st["head"]) >= 7


async def test_diverged_edit_locks_repo(repos):
    """Desktop pushes a conflicting change; a local edit then conflicts → locked."""
    work = Path(repos["work"])
    desktop = work.parent / "desktop"
    _run(work.parent, "clone", str(repos["bare"]), str(desktop))
    _run(desktop, "config", "user.email", "d@local")
    _run(desktop, "config", "user.name", "Desktop")
    (desktop / "作品A" / "第01章.md").write_text("desktop-change\n", encoding="utf-8")
    _run(desktop, "commit", "-am", "desktop edit")
    _run(desktop, "push", "origin", "main")
    # Local conflicting edit (no fetch) then commit+push → reject → rebase → conflict → locked
    (work / "作品A" / "第01章.md").write_text("jyzrox-change\n", encoding="utf-8")
    with pytest.raises(novel_git.NovelLocked):
        await novel_git.commit_and_push(str(work), "作品A/第01章.md", "edit: 作品A/第01章.md")
    st = await novel_git.status(str(work))
    assert st["locked"] is True
    # reset escape hatch clears lock and matches origin
    await novel_git.reset_to_origin(str(work), "main")
    st2 = await novel_git.status(str(work))
    assert st2["locked"] is False
    assert (work / "作品A" / "第01章.md").read_text() == "desktop-change\n"
