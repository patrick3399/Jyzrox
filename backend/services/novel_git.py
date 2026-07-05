"""Git subprocess wrapper for the novel module — the ONLY place that shells git.

All calls use asyncio.create_subprocess_exec (never a shell), 30s timeout.
Callers MUST hold the Redis lock `novel:git:lock` for any mutating operation;
serialization is the caller's responsibility (see routers/worker).
"""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path

_TIMEOUT = 30
_LOCK_SENTINEL = ".jyzrox-locked"
# A revision reaching git must be a bare object name: hex sha1/sha256 (or a short
# prefix). This blocks argument injection (e.g. rev="--output=/path") from ever
# being parsed as a git option — the UI only ever passes commit hashes.
_REV_RE = re.compile(r"\A[0-9a-fA-F]{4,64}\Z")
_AUTHOR_ENV = {
    "GIT_AUTHOR_NAME": "Jyzrox",
    "GIT_AUTHOR_EMAIL": "jyzrox@local",
    "GIT_COMMITTER_NAME": "Jyzrox",
    "GIT_COMMITTER_EMAIL": "jyzrox@local",
}


class NovelGitError(Exception):
    pass


class NovelLocked(Exception):
    pass


async def _git(repo: str | Path, *args: str, env_extra: dict | None = None) -> tuple[int, str, str]:
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    proc = await asyncio.create_subprocess_exec(
        "git",
        "-C",
        str(repo),
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=_TIMEOUT)
    except TimeoutError:
        proc.kill()
        await proc.wait()  # reap the killed process (avoid a zombie / ResourceWarning)
        raise NovelGitError(f"git {' '.join(args)} timed out")
    return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")


def _lock_path(repo: str | Path) -> Path:
    return Path(repo) / _LOCK_SENTINEL


def _is_locked(repo: str | Path) -> bool:
    return _lock_path(repo).exists()


async def head_sha(repo: str | Path) -> str:
    code, out, err = await _git(repo, "rev-parse", "HEAD")
    if code != 0:
        raise NovelGitError(err)
    return out.strip()


async def _current_branch(repo: str | Path) -> str:
    _, out, _ = await _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    return out.strip() or "main"


async def status(repo: str | Path) -> dict:
    head = await head_sha(repo)
    _, porcelain, _ = await _git(repo, "status", "--porcelain")
    clean = porcelain.strip() == ""
    branch = await _current_branch(repo)
    ahead = behind = 0
    code, out, _ = await _git(repo, "rev-list", "--left-right", "--count", f"origin/{branch}...HEAD")
    if code == 0 and out.strip():
        parts = out.split()
        behind, ahead = int(parts[0]), int(parts[1])
    return {
        "head": head,
        "ahead": ahead,
        "behind": behind,
        "clean": clean,
        "locked": _is_locked(repo),
    }


async def fetch(repo: str | Path) -> None:
    code, _, err = await _git(repo, "fetch", "origin")
    if code != 0:
        raise NovelGitError(err)


async def pull_ff(repo: str | Path) -> bool:
    branch = await _current_branch(repo)
    code, _, _ = await _git(repo, "merge", "--ff-only", f"origin/{branch}")
    return code == 0


async def commit_file(repo: str | Path, rel_path: str, message: str) -> str:
    code, _, err = await _git(repo, "add", "--", rel_path)
    if code != 0:
        raise NovelGitError(err)
    code, out, err = await _git(repo, "commit", "-m", message, "--", rel_path, env_extra=_AUTHOR_ENV)
    if code != 0:
        # Saving identical content leaves a clean tree — treat as a no-op edit
        # rather than surfacing git's "nothing to commit" as a 500.
        if "nothing to commit" in out or "nothing to commit" in err:
            return await head_sha(repo)
        raise NovelGitError(err)
    return await head_sha(repo)


async def push(repo: str | Path) -> bool:
    branch = await _current_branch(repo)
    code, _, err = await _git(repo, "push", "origin", branch)
    if code == 0:
        return True
    if "non-fast-forward" in err or "rejected" in err or "fetch first" in err:
        return False
    raise NovelGitError(err)


async def commit_and_push(repo: str | Path, rel_path: str, message: str) -> dict:
    new_head = await commit_file(repo, rel_path, message)
    if await push(repo):
        return {"head": new_head, "pushed": True}
    # non-fast-forward → rebase once, retry push once
    await fetch(repo)
    branch = await _current_branch(repo)
    code, _, _ = await _git(repo, "rebase", f"origin/{branch}")
    if code != 0:
        await _git(repo, "rebase", "--abort")
        _lock_path(repo).write_text("conflict on commit_and_push\n", encoding="utf-8")
        raise NovelLocked(rel_path)
    if await push(repo):
        return {"head": await head_sha(repo), "pushed": True}
    return {"head": await head_sha(repo), "pushed": False}  # 214 offline etc.


async def log_file(repo: str | Path, rel_path: str, limit: int = 50) -> list[dict]:
    code, out, err = await _git(repo, "log", f"-{limit}", "--pretty=format:%H%x1f%cI%x1f%s", "--", rel_path)
    if code != 0:
        raise NovelGitError(err)
    rows = []
    for line in out.splitlines():
        h, date, msg = line.split("\x1f", 2)
        rows.append({"hash": h, "date": date, "message": msg})
    return rows


async def diff_file(repo: str | Path, rel_path: str, rev: str) -> str:
    if not _REV_RE.match(rev):
        raise NovelGitError(f"invalid rev: {rev!r}")
    # --end-of-options is a second guard: even a validated rev can never be
    # reinterpreted as a git option.
    code, out, err = await _git(repo, "show", "--end-of-options", rev, "--", rel_path)
    if code != 0:
        raise NovelGitError(err)
    return out


async def reset_to_origin(repo: str | Path, branch: str | None = None) -> None:
    # Default to the clone's actual branch — the 214 repo uses `master`, so a
    # hardcoded `main` would reset to a non-existent origin/main and fail.
    if branch is None:
        branch = await _current_branch(repo)
    await _git(repo, "rebase", "--abort")  # ignore failure
    await fetch(repo)
    code, _, err = await _git(repo, "reset", "--hard", f"origin/{branch}")
    if code != 0:
        raise NovelGitError(err)
    _lock_path(repo).unlink(missing_ok=True)
