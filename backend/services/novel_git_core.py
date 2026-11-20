"""Low-level git runner, error types and lock sentinel helpers for the novel module."""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path

from services import novel_remote

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
