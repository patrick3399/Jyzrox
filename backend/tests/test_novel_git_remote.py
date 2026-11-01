import subprocess

import pytest

from services import novel_git, novel_remote


def _run(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _make_origin(tmp_path, name, branch="main", files=None):
    """Bare repo `name.git` seeded with `files` via a scratch clone."""
    bare = tmp_path / f"{name}.git"
    bare.mkdir()
    _run(bare, "init", "--bare", "-b", branch)
    scratch = tmp_path / f"scratch-{name}"
    _run(tmp_path, "clone", str(bare), str(scratch))
    _run(scratch, "config", "user.email", "t@l")
    _run(scratch, "config", "user.name", "t")
    for rel, body in (files or {}).items():
        p = scratch / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    if files:
        _run(scratch, "add", ".")
        _run(scratch, "commit", "-m", f"seed {name}")
        _run(scratch, "push", "origin", branch)
    return bare


@pytest.fixture(autouse=True)
def _allow_local_protocol(monkeypatch):
    monkeypatch.setattr(novel_git, "_REMOTE_PROTOCOLS", "ssh:file")


@pytest.fixture()
def clone(tmp_path):
    hub = _make_origin(tmp_path, "hub", files={"作品A/01.md": "v1\n"})
    work = tmp_path / "work"
    _run(tmp_path, "clone", str(hub), str(work))
    _run(work, "config", "user.email", "t@l")
    _run(work, "config", "user.name", "t")
    return {"hub": hub, "work": work, "tmp": tmp_path}


def test_build_env_always_pins_managed_ssh_command_over_ambient_env(monkeypatch):
    monkeypatch.setattr(novel_remote, "ssh_command", lambda: "ssh -i /k")
    monkeypatch.setenv("GIT_SSH_COMMAND", "ambient")
    assert novel_git._build_env(None)["GIT_SSH_COMMAND"] == "ssh -i /k"


async def test_get_remote_url(clone):
    assert await novel_git.get_remote_url(clone["work"]) == str(clone["hub"])
    assert await novel_git.get_remote_url(clone["tmp"] / "nope") is None


async def test_relation_related_for_same_history_other_location(clone):
    mirror = clone["tmp"] / "mirror.git"
    _run(clone["tmp"], "clone", "--bare", str(clone["hub"]), str(mirror))
    assert await novel_git.history_relation(clone["work"], str(mirror)) == "related"


async def test_relation_unrelated_when_histories_do_not_share_a_root(clone):
    other = _make_origin(clone["tmp"], "other", files={"x.md": "z\n"})
    assert await novel_git.history_relation(clone["work"], str(other)) == "unrelated"


async def test_relation_remote_empty(clone):
    empty = _make_origin(clone["tmp"], "empty")
    assert await novel_git.history_relation(clone["work"], str(empty)) == "remote_empty"


async def test_relation_branch_mismatch_when_default_branch_differs(clone):
    mirror = clone["tmp"] / "mirror.git"
    _run(clone["tmp"], "clone", "--bare", str(clone["hub"]), str(mirror))
    _run(mirror, "branch", "master", "main")
    _run(mirror, "symbolic-ref", "HEAD", "refs/heads/master")
    assert await novel_git.history_relation(clone["work"], str(mirror)) == "branch_mismatch"


async def test_relation_unreachable_raises(clone):
    with pytest.raises(novel_git.NovelGitError):
        await novel_git.history_relation(clone["work"], str(clone["tmp"] / "missing.git"))


async def test_set_remote_url_repoints_origin(clone):
    mirror = clone["tmp"] / "mirror.git"
    _run(clone["tmp"], "clone", "--bare", str(clone["hub"]), str(mirror))
    await novel_git.set_remote_url(clone["work"], str(mirror))
    assert await novel_git.get_remote_url(clone["work"]) == str(mirror)


async def test_clone_replace_swaps_tree_and_clears_lock_sentinel(clone):
    other = _make_origin(clone["tmp"], "other", files={"新作/01.md": "new\n"})
    work = clone["work"]
    (work / ".jyzrox-locked").write_text("conflict\n")
    (work / "untracked.md").write_text("local only\n")
    await novel_git.clone_replace(work, str(other))
    assert (work / "新作" / "01.md").read_text() == "new\n"
    assert not (work / "作品A").exists()
    assert not (work / "untracked.md").exists()
    assert not (work / ".jyzrox-locked").exists()
    assert not (work / ".jyzrox-clone-tmp").exists()
    assert await novel_git.get_remote_url(work) == str(other)


async def test_clone_replace_failure_keeps_old_tree(clone):
    work = clone["work"]
    with pytest.raises(novel_git.NovelGitError):
        await novel_git.clone_replace(work, str(clone["tmp"] / "missing.git"))
    assert (work / "作品A" / "01.md").read_text() == "v1\n"
    assert not (work / ".jyzrox-clone-tmp").exists()
    assert await novel_git.get_remote_url(work) == str(clone["hub"])


async def test_clone_into_missing_repo_dir_creates_it(clone):
    target = clone["tmp"] / "fresh"
    await novel_git.clone_replace(target, str(clone["hub"]))
    assert (target / "作品A" / "01.md").exists()


async def test_status_survives_empty_clone_with_unborn_head(clone):
    empty = _make_origin(clone["tmp"], "empty")
    target = clone["tmp"] / "fresh"
    await novel_git.clone_replace(target, str(empty))
    st = await novel_git.status(target)  # used to raise on rev-parse HEAD
    assert st["head"] == "" and st["clean"] is True


async def test_first_commit_on_empty_clone_pushes_to_the_clones_own_branch(clone):
    empty = _make_origin(clone["tmp"], "empty", branch="trunk")
    target = clone["tmp"] / "fresh"
    await novel_git.clone_replace(target, str(empty))
    _run(target, "config", "user.email", "t@l")
    _run(target, "config", "user.name", "t")
    (target / "a.md").write_text("x\n")
    result = await novel_git.commit_and_push(str(target), "a.md", "create: a.md")
    assert result["pushed"] is True
    out = subprocess.run(["git", "-C", str(empty), "branch"], capture_output=True, text=True).stdout
    assert "trunk" in out
