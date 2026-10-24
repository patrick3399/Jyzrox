"""Managed SSH identity + remote URL validation for the novel hub.

Shells ssh-keygen/ssh-keyscan only (git lives in novel_git). The private key
never leaves this module: callers get the public half and a fingerprint.
"""

from __future__ import annotations

import asyncio
import re
import shlex
from dataclasses import dataclass
from pathlib import Path

from core.config import settings

_TIMEOUT = 15
_KEY_TYPES = "ed25519,ecdsa,rsa"
_FP_RE = re.compile(r"SHA256:[A-Za-z0-9+/=]+")
_USER = r"[A-Za-z_][A-Za-z0-9_.-]*"
_HOST = r"[A-Za-z0-9][A-Za-z0-9.-]*"
_PATH = r"[A-Za-z0-9_./~][A-Za-z0-9_./~+-]*"
_SCP_RE = re.compile(rf"\A{_USER}@(?P<host>{_HOST}):(?P<path>{_PATH})\Z")
_SSH_RE = re.compile(rf"\Assh://{_USER}@(?P<host>{_HOST})(?::(?P<port>\d{{1,5}}))?/(?P<path>{_PATH})\Z")


class InvalidRemote(ValueError):
    pass


class KeyExists(Exception):
    pass


class FingerprintMismatch(Exception):
    pass


class RemoteToolError(Exception):
    pass


@dataclass(frozen=True)
class RemoteTarget:
    url: str
    host: str
    port: int | None


def parse_remote_url(url: str) -> RemoteTarget:
    url = (url or "").strip()
    m = _SSH_RE.match(url)
    if m:
        port = int(m["port"]) if m["port"] else None
        if port is not None and not 1 <= port <= 65535:
            raise InvalidRemote("port out of range")
        return RemoteTarget(url, m["host"], port)
    m = _SCP_RE.match(url)
    if m:
        return RemoteTarget(url, m["host"], None)
    raise InvalidRemote("expected user@host:path or ssh://user@host[:port]/path")


def ssh_dir() -> Path:
    return Path(settings.novel_ssh_dir)


def key_path() -> Path:
    return ssh_dir() / "id_ed25519"


def known_hosts_path() -> Path:
    return ssh_dir() / "known_hosts"


def has_managed_key() -> bool:
    return key_path().is_file()


def ssh_command() -> str:
    """GIT_SSH_COMMAND pinned to the managed identity — the only identity there is.

    Always returned, even before a key exists: ssh then fails with a clear
    error instead of silently trying whatever is in ~/.ssh.
    """
    return " ".join(
        [
            "ssh",
            "-i",
            shlex.quote(str(key_path())),
            "-o",
            f"UserKnownHostsFile={shlex.quote(str(known_hosts_path()))}",
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "ConnectTimeout=10",
        ]
    )


def public_key() -> str | None:
    pub = Path(f"{key_path()}.pub")
    return pub.read_text(encoding="utf-8").strip() if pub.is_file() else None


async def _run(*args: str, stdin: bytes | None = None) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.PIPE if stdin is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(stdin), timeout=_TIMEOUT)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise RemoteToolError(f"{args[0]} timed out")
    return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")


async def key_fingerprint() -> str | None:
    pub = Path(f"{key_path()}.pub")
    if not pub.is_file():
        return None
    code, out, _ = await _run("ssh-keygen", "-lf", str(pub))
    m = _FP_RE.search(out) if code == 0 else None
    return m.group(0) if m else None


async def generate_key(*, overwrite: bool) -> str:
    d = ssh_dir()
    d.mkdir(mode=0o700, parents=True, exist_ok=True)
    if key_path().exists():
        if not overwrite:
            raise KeyExists()
        key_path().unlink()
        Path(f"{key_path()}.pub").unlink(missing_ok=True)
    code, _, err = await _run(
        "ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "jyzrox-novel", "-f", str(key_path())
    )
    if code != 0:
        raise RemoteToolError(err.strip()[:300])
    known_hosts_path().touch(mode=0o600, exist_ok=True)
    pub = public_key()
    if pub is None:
        raise RemoteToolError("public key missing after generation")
    return pub


def _known_hosts_name(target: RemoteTarget) -> str:
    return f"[{target.host}]:{target.port}" if target.port else target.host


async def scan_host_keys(target: RemoteTarget) -> list[dict]:
    args = ["ssh-keyscan", "-T", "5", "-t", _KEY_TYPES]
    if target.port:
        args += ["-p", str(target.port)]
    code, out, err = await _run(*args, "--", target.host)
    lines = [ln for ln in out.splitlines() if ln and not ln.startswith("#")]
    if code != 0 or not lines:
        raise RemoteToolError((err.strip() or "no host keys returned")[:300])
    keys = []
    for ln in lines:
        c, fp_out, _ = await _run("ssh-keygen", "-lf", "-", stdin=(ln + "\n").encode())
        m = _FP_RE.search(fp_out) if c == 0 else None
        if m:
            keys.append({"type": ln.split()[1].removeprefix("ssh-"), "fingerprint": m.group(0), "line": ln})
    if not keys:
        raise RemoteToolError("could not fingerprint host keys")
    return keys


async def trust_host(target: RemoteTarget, fingerprint: str) -> None:
    """Re-scan and persist only the key whose fingerprint the admin confirmed.

    Re-scanning (instead of trusting the line from the earlier scan) means the
    admin approves a fingerprint, not an opaque blob a client could swap.
    """
    keys = await scan_host_keys(target)
    match = next((k for k in keys if k["fingerprint"] == fingerprint), None)
    if match is None:
        raise FingerprintMismatch()
    ssh_dir().mkdir(mode=0o700, parents=True, exist_ok=True)
    kh = known_hosts_path()
    kh.touch(mode=0o600, exist_ok=True)
    existing = kh.read_text(encoding="utf-8").splitlines()
    if match["line"] not in existing:
        with kh.open("a", encoding="utf-8") as f:
            f.write(match["line"] + "\n")


async def is_host_trusted(target: RemoteTarget) -> bool:
    if not known_hosts_path().is_file():
        return False
    code, _, _ = await _run("ssh-keygen", "-F", _known_hosts_name(target), "-f", str(known_hosts_path()))
    return code == 0
