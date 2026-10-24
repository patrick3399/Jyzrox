"""Git subprocess wrapper for the novel module — the ONLY place that shells git.

All calls use asyncio.create_subprocess_exec (never a shell), 30s timeout.
Callers MUST hold the Redis lock `novel:git:lock` for any mutating operation;
serialization is the caller's responsibility (see routers/worker).
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
from pathlib import Path

from services import novel_remote

logger = logging.getLogger(__name__)

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


_REMOTE_PROTOCOLS = "ssh"  # URLs we hand to git come from the admin UI: ssh only


def _build_env(env_extra: dict | None) -> dict:
    env = os.environ.copy()
    env["GIT_SSH_COMMAND"] = novel_remote.ssh_command()  # managed identity is the only identity
    if env_extra:
        env.update(env_extra)
    return env


def _remote_env() -> dict:
    return {"GIT_ALLOW_PROTOCOL": _REMOTE_PROTOCOLS, "GIT_TERMINAL_PROMPT": "0"}


async def _git(
    repo: str | Path, *args: str, env_extra: dict | None = None, timeout: float | None = None
) -> tuple[int, str, str]:
    env = _build_env(env_extra)
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
        out, err = await asyncio.wait_for(proc.communicate(), timeout=_TIMEOUT if timeout is None else timeout)
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
    code, out, _ = await _git(repo, "symbolic-ref", "--short", "HEAD")
    if code == 0 and out.strip():
        return out.strip()
    _, out, _ = await _git(repo, "rev-parse", "--abbrev-ref", "HEAD")  # detached HEAD
    return out.strip() or "main"


async def status(repo: str | Path) -> dict:
    code, out, _ = await _git(repo, "rev-parse", "HEAD")
    head = out.strip() if code == 0 else ""  # unborn HEAD (empty remote)
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
    """Commit locally, then try to publish. The local commit is always reported.

    The two legs fail independently and must be reported independently. A
    generic push failure (unreachable host, SSH/auth trouble) used to raise out
    of here *after* commit_file had already advanced HEAD, so the endpoint
    returned 500 while the author's edit was committed — audit, the WebSocket
    event and the reindex were all skipped, and a retry from the client then hit
    a stale base_sha because HEAD had moved. Report ``pushed: False`` with the
    reason instead; the work is safe in local history and the next successful
    push (or a sync) carries it to the remote.

    A rebase conflict still raises NovelLocked: that is not a transport problem
    but a repo state needing manual resolution, and the sentinel it writes makes
    every later write fail fast until a human clears it.
    """
    new_head = await commit_file(repo, rel_path, message)
    try:
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
        return {"head": await head_sha(repo), "pushed": False}  # remote hub offline etc.
    except NovelLocked:
        raise
    except NovelGitError as exc:
        logger.warning("novel push failed after a successful local commit: %s", exc)
        return {"head": await head_sha(repo), "pushed": False, "push_error": str(exc)}


async def log_file(repo: str | Path, rel_path: str, limit: int = 50) -> list[dict]:
    code, out, err = await _git(repo, "log", f"-{limit}", "--pretty=format:%H%x1f%cI%x1f%s", "--", rel_path)
    if code != 0:
        raise NovelGitError(err)
    rows = []
    for line in out.splitlines():
        h, date, msg = line.split("\x1f", 2)
        rows.append({"hash": h, "date": date, "message": msg})
    return rows


async def diff_file(repo: str | Path, rel_path: str, rev: str, base: str | None = None) -> str:
    """Unified diff for one file: `rev` against its parent, or against `base`
    when given (compare any two revisions)."""
    if not _REV_RE.match(rev):
        raise NovelGitError(f"invalid rev: {rev!r}")
    # --end-of-options is a second guard: even a validated rev can never be
    # reinterpreted as a git option.
    if base is None:
        args = ("show", "--end-of-options", rev, "--", rel_path)
    else:
        if not _REV_RE.match(base):
            raise NovelGitError(f"invalid rev: {base!r}")
        args = ("diff", "--end-of-options", base, rev, "--", rel_path)
    code, out, err = await _git(repo, *args)
    if code != 0:
        raise NovelGitError(err)
    return out


async def file_at_rev(repo: str | Path, rel_path: str, rev: str) -> str:
    """The file's content as of `rev` — the source for a revert.

    `rev:path` is resolved from the repo root (git runs with -C repo). The rev
    is hex-validated, so the combined argument can never look like an option.
    """
    if not _REV_RE.match(rev):
        raise NovelGitError(f"invalid rev: {rev!r}")
    code, out, err = await _git(repo, "show", "--end-of-options", f"{rev}:{rel_path}")
    if code != 0:
        # Also the "file did not exist at that revision" path.
        raise NovelGitError(err)
    return out


async def reset_to_origin(repo: str | Path, branch: str | None = None) -> None:
    # Default to the clone's actual branch — a hub repo may use `master`, so a
    # hardcoded `main` would reset to a non-existent origin/main and fail.
    if branch is None:
        branch = await _current_branch(repo)
    await _git(repo, "rebase", "--abort")  # ignore failure
    await fetch(repo)
    code, _, err = await _git(repo, "reset", "--hard", f"origin/{branch}")
    if code != 0:
        raise NovelGitError(err)
    _lock_path(repo).unlink(missing_ok=True)


async def get_remote_url(repo: str | Path) -> str | None:
    code, out, _ = await _git(repo, "remote", "get-url", "origin")
    return out.strip() if code == 0 and out.strip() else None


async def ls_remote(url: str) -> dict:
    """Probe a remote without touching any repo. `url` MUST be pre-validated by
    novel_remote.parse_remote_url (never starts with '-', ssh forms only)."""
    code, out, err = await _git(".", "ls-remote", "--symref", "--", url, "HEAD", env_extra=_remote_env())
    if code != 0:
        return {"ok": False, "empty": False, "default_branch": None, "error": err.strip()[:300]}
    branch = None
    for line in out.splitlines():
        if line.startswith("ref: "):
            branch = line.split()[1].removeprefix("refs/heads/")
    return {"ok": True, "empty": not out.strip(), "default_branch": branch, "error": ""}


async def history_relation(repo: str | Path, url: str) -> str:
    probe = await ls_remote(url)
    if not probe["ok"]:
        raise NovelGitError(probe["error"] or "remote unreachable")
    if probe["empty"]:
        return "remote_empty"
    if probe["default_branch"] != await _current_branch(repo):
        return "branch_mismatch"
    code, _, err = await _git(repo, "fetch", "--no-tags", "--", url, "HEAD", env_extra=_remote_env())
    if code != 0:
        raise NovelGitError(err.strip()[:300])
    code, _, _ = await _git(repo, "merge-base", "HEAD", "FETCH_HEAD")
    return "related" if code == 0 else "unrelated"


async def set_remote_url(repo: str | Path, url: str) -> None:
    verb = "set-url" if await get_remote_url(repo) else "add"
    args = ("remote", verb, "origin", url)
    code, _, err = await _git(repo, *args, env_extra=_remote_env())
    if code != 0:
        raise NovelGitError(err.strip()[:300])


def _swap_in(root: Path, tmp: Path) -> None:
    for child in list(root.iterdir()):
        if child == tmp:
            continue
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()
    for child in list(tmp.iterdir()):
        child.rename(root / child.name)
    tmp.rmdir()


async def clone_replace(repo: str | Path, url: str) -> None:
    """Replace the working clone with a fresh clone of `url`.

    The repo directory is usually a bind-mount root, so it cannot be renamed
    aside: clone into a scratch dir inside it, and only after the clone
    succeeded wipe the old contents and move the new ones up. A failed clone
    therefore never touches the existing tree. Local state is disposable by
    design (the hub is the source of truth). Caller MUST hold the git lock.
    """
    root = Path(repo)
    root.mkdir(parents=True, exist_ok=True)
    tmp = root / ".jyzrox-clone-tmp"
    await asyncio.to_thread(shutil.rmtree, tmp, True)
    code, _, err = await _git(root, "clone", "--", url, str(tmp), env_extra=_remote_env(), timeout=120)
    if code != 0:
        await asyncio.to_thread(shutil.rmtree, tmp, True)
        raise NovelGitError(err.strip()[:300])
    await asyncio.to_thread(_swap_in, root, tmp)
