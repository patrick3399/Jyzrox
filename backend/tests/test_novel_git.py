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


async def test_reset_to_origin_defaults_to_current_branch_not_main(tmp_path):
    """A hub repo may use `master`; reset_to_origin() with no branch must target it."""
    bare = tmp_path / "origin.git"
    bare.mkdir()
    _run(bare, "init", "--bare", "-b", "master")
    work = tmp_path / "work"
    _run(tmp_path, "clone", str(bare), str(work))
    _run(work, "config", "user.email", "jyzrox@local")
    _run(work, "config", "user.name", "Jyzrox")
    (work / "第01章.md").write_text("v1\n", encoding="utf-8")
    _run(work, "add", ".")
    _run(work, "commit", "-m", "init")
    _run(work, "push", "origin", "master")
    # Dirty the working tree, then reset without specifying a branch.
    (work / "第01章.md").write_text("local mess\n", encoding="utf-8")
    await novel_git.reset_to_origin(str(work))  # no branch arg → must use `master`
    assert (work / "第01章.md").read_text() == "v1\n"


async def test_git_timeout_reaps_the_killed_process(monkeypatch):
    """On timeout the subprocess must be killed AND reaped (await wait())."""
    import asyncio as _asyncio

    reaped = {"kill": False, "wait": False}

    class _FakeProc:
        returncode = -9

        async def communicate(self):
            await _asyncio.sleep(10)  # never completes within the patched timeout

        def kill(self):
            reaped["kill"] = True

        async def wait(self):
            reaped["wait"] = True

    async def _fake_exec(*args, **kwargs):
        return _FakeProc()

    monkeypatch.setattr(novel_git.asyncio, "create_subprocess_exec", _fake_exec)
    monkeypatch.setattr(novel_git, "_TIMEOUT", 0.05)
    with pytest.raises(novel_git.NovelGitError):
        await novel_git.head_sha("/tmp")
    assert reaped["kill"] is True
    assert reaped["wait"] is True


async def test_diff_file_returns_commit_diff(repos):
    work = str(repos["work"])
    head = await novel_git.head_sha(work)
    diff = await novel_git.diff_file(work, "作品A/第01章.md", head)
    assert "v1" in diff


async def test_diff_file_rejects_option_injection(repos, tmp_path):
    """A crafted `rev` starting with `--` must not reach git as an option.

    `git show --output=<path>` would otherwise write the diff to an arbitrary
    file (argument injection), even though we never invoke a shell.
    """
    work = str(repos["work"])
    sentinel = tmp_path / "pwned.txt"
    with pytest.raises(novel_git.NovelGitError):
        await novel_git.diff_file(work, "作品A/第01章.md", f"--output={sentinel}")
    assert not sentinel.exists()


async def test_diff_file_with_base_compares_two_revisions(repos):
    """base=<rev> diffs two arbitrary commits, not just a commit against its parent."""
    work = str(repos["work"])
    first = await novel_git.head_sha(work)
    (Path(work) / "作品A" / "第01章.md").write_text("v2\n", encoding="utf-8")
    await novel_git.commit_and_push(work, "作品A/第01章.md", "edit: v2")
    second = await novel_git.head_sha(work)
    diff = await novel_git.diff_file(work, "作品A/第01章.md", second, base=first)
    assert "-v1" in diff and "+v2" in diff


async def test_diff_file_rejects_option_injection_in_base(repos, tmp_path):
    """The compare base takes the same hex-only validation as `rev`."""
    work = str(repos["work"])
    sentinel = tmp_path / "pwned.txt"
    head = await novel_git.head_sha(work)
    with pytest.raises(novel_git.NovelGitError):
        await novel_git.diff_file(work, "作品A/第01章.md", head, base=f"--output={sentinel}")
    assert not sentinel.exists()


async def test_file_at_rev_returns_old_content(repos):
    work = str(repos["work"])
    first = await novel_git.head_sha(work)
    (Path(work) / "作品A" / "第01章.md").write_text("v2\n", encoding="utf-8")
    await novel_git.commit_and_push(work, "作品A/第01章.md", "edit: v2")
    assert await novel_git.file_at_rev(work, "作品A/第01章.md", first) == "v1\n"


async def test_file_at_rev_rejects_option_injection(repos, tmp_path):
    """`rev` reaches git glued to the path (`rev:path`); it must stay hex-only."""
    work = str(repos["work"])
    sentinel = tmp_path / "pwned.txt"
    with pytest.raises(novel_git.NovelGitError):
        await novel_git.file_at_rev(work, "作品A/第01章.md", f"--output={sentinel}")
    assert not sentinel.exists()


async def test_file_at_rev_raises_when_file_absent_at_that_revision(repos):
    """Reverting a path that did not exist yet must fail loudly, not return ''."""
    work = str(repos["work"])
    first = await novel_git.head_sha(work)
    (Path(work) / "作品A" / "第02章.md").write_text("new\n", encoding="utf-8")
    await novel_git.commit_and_push(work, "作品A/第02章.md", "create: 第02章")
    with pytest.raises(novel_git.NovelGitError):
        await novel_git.file_at_rev(work, "作品A/第02章.md", first)


async def test_commit_and_push_noop_when_content_unchanged(repos):
    """Saving identical content must be a no-op, not a `nothing to commit` error."""
    work = str(repos["work"])
    result = await novel_git.commit_and_push(work, "作品A/第01章.md", "edit: noop")
    assert result["pushed"] is True


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


async def test_unreachable_remote_still_reports_the_local_commit(repos):
    """A transport failure must not discard the fact that the commit landed.

    push() raises NovelGitError for anything that is not a non-fast-forward, and
    that used to propagate out of commit_and_push *after* commit_file had already
    advanced HEAD: the endpoint answered 500 while the edit sat committed, audit
    and the reindex never ran, and the client's retry then hit a stale base_sha.
    """
    work = str(repos["work"])
    _run(work, "remote", "set-url", "origin", "/nonexistent/definitely-not-a-repo.git")
    (Path(work) / "作品A" / "第01章.md").write_text("v2\n", encoding="utf-8")

    head_before = await novel_git.head_sha(work)
    result = await novel_git.commit_and_push(work, "作品A/第01章.md", "edit: unreachable remote")

    assert result["pushed"] is False
    assert result["push_error"]
    # The commit is real and reported, so the client can keep writing.
    assert result["head"] != head_before
    assert result["head"] == await novel_git.head_sha(work)
    log = await novel_git.log_file(work, "作品A/第01章.md")
    assert log[0]["message"] == "edit: unreachable remote"


async def test_unpushed_commit_shows_up_as_ahead(repos):
    """`ahead` is what the UI's unpushed badge reads, so it must reflect this."""
    work = str(repos["work"])
    _run(work, "remote", "set-url", "origin", "/nonexistent/definitely-not-a-repo.git")
    (Path(work) / "作品A" / "第01章.md").write_text("v2\n", encoding="utf-8")

    await novel_git.commit_and_push(work, "作品A/第01章.md", "edit: offline")

    st = await novel_git.status(work)
    assert st["ahead"] == 1
    assert st["locked"] is False


async def test_a_later_push_carries_the_deferred_commit(repos):
    """Nothing is lost: once the remote is reachable the commit publishes."""
    work = str(repos["work"])
    good_url = str(repos["bare"])
    _run(work, "remote", "set-url", "origin", "/nonexistent/definitely-not-a-repo.git")
    (Path(work) / "作品A" / "第01章.md").write_text("v2\n", encoding="utf-8")
    first = await novel_git.commit_and_push(work, "作品A/第01章.md", "edit: offline")
    assert first["pushed"] is False

    _run(work, "remote", "set-url", "origin", good_url)
    (Path(work) / "作品A" / "第01章.md").write_text("v3\n", encoding="utf-8")
    second = await novel_git.commit_and_push(work, "作品A/第01章.md", "edit: back online")

    assert second["pushed"] is True
    st = await novel_git.status(work)
    assert st["ahead"] == 0


async def test_rebase_conflict_still_locks_the_repo(repos, tmp_path):
    """A conflict is a repo state needing a human, not a transport blip — it must
    keep raising NovelLocked and leave the sentinel behind."""
    work = str(repos["work"])
    other = tmp_path / "other"
    _run(tmp_path, "clone", str(repos["bare"]), str(other))
    _run(other, "config", "user.email", "other@local")
    _run(other, "config", "user.name", "Other")
    (other / "作品A" / "第01章.md").write_text("theirs\n", encoding="utf-8")
    _run(other, "add", ".")
    _run(other, "commit", "-m", "theirs")
    _run(other, "push", "origin", "main")

    (Path(work) / "作品A" / "第01章.md").write_text("mine\n", encoding="utf-8")
    with pytest.raises(novel_git.NovelLocked):
        await novel_git.commit_and_push(work, "作品A/第01章.md", "edit: mine")

    assert (await novel_git.status(work))["locked"] is True
