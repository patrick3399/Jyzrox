"""gallery-dl isolated venv management.

Provides an independent venv on a Docker volume (/opt/gallery-dl) so
gallery-dl can be upgraded/rolled-back via API without rebuilding the
container.

Volume layout:
    /opt/gallery-dl/
    ├── active -> v1/       ← symlink to current version
    ├── v1/                 ← initial venv
    │   └── bin/gallery-dl
    └── v2/                 ← after first upgrade
"""

import asyncio
import fcntl
import logging
import re
import shutil
import sys
from contextlib import asynccontextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

VENV_BASE = Path("/opt/gallery-dl")
VENV_ACTIVE = VENV_BASE / "active"
GDL_BIN = VENV_ACTIVE / "bin" / "gallery-dl"

# Pinned baseline for the initial venv. Kept intentionally below the latest
# PyPI release so the admin online-upgrade path always has a gap to exercise.
INITIAL_GDL_VERSION = "1.32.1"

_VERSION_DIR_RE = re.compile(r"^v\d+$")

_gdl_bin_cache: str | None = None

_ACTIVE_DOWNLOAD_STATUSES = ("queued", "paused", "running")


def _venv_create_cmd(target: Path) -> list[str]:
    """Create an isolated venv that owns its gallery-dl entry point."""
    return [sys.executable, "-m", "venv", str(target)]


def get_gdl_bin() -> str:
    """Return gallery-dl binary path — venv if available, else system PATH fallback."""
    global _gdl_bin_cache
    if _gdl_bin_cache is None:
        _gdl_bin_cache = str(GDL_BIN) if GDL_BIN.exists() else "gallery-dl"
    return _gdl_bin_cache


def get_gdl_exec_cmd() -> list[str]:
    """Return a command prefix that holds a shared venv lock until exit.

    The small Python launcher acquires the lock and then ``exec`` replaces it
    with gallery-dl, so the lock follows the exact subprocess lifetime without
    serialising concurrent downloads.
    """
    return [
        sys.executable,
        "-m",
        "gallery_dl_exec",
        str(VENV_BASE / ".lifecycle.lock"),
        get_gdl_bin(),
    ]


def invalidate_gdl_bin_cache() -> None:
    """Clear cached binary path. Called after upgrade/rollback."""
    global _gdl_bin_cache
    _gdl_bin_cache = None


async def _run(cmd: list[str], timeout: float = 300) -> tuple[int, str, str]:
    """Run a subprocess and return (returncode, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise
    rc = proc.returncode
    # After communicate() returns, returncode is guaranteed non-None
    return rc if rc is not None else -1, stdout.decode(), stderr.decode()


def _version_dirs() -> list[Path]:
    """Return sorted list of v{N} directories under VENV_BASE."""
    if not VENV_BASE.exists():
        return []
    return sorted(
        (d for d in VENV_BASE.iterdir() if d.is_dir() and _VERSION_DIR_RE.match(d.name)),
        key=lambda d: int(d.name[1:]),
    )


def _next_version_dir() -> Path:
    """Find the next available v{N} directory."""
    existing = _version_dirs()
    if not existing:
        return VENV_BASE / "v1"
    last_num = int(existing[-1].name[1:])
    return VENV_BASE / f"v{last_num + 1}"


def _current_version_dir() -> Path | None:
    """Return the directory the 'active' symlink points to, or None."""
    if VENV_ACTIVE.is_symlink():
        target = VENV_ACTIVE.resolve()
        if target.exists():
            return target
    return None


def _previous_version_dir() -> Path | None:
    """Find the previous version directory (one before current)."""
    current = _current_version_dir()
    if current is None:
        return None
    dirs = _version_dirs()
    for i, d in enumerate(dirs):
        if d.resolve() == current and i > 0:
            return dirs[i - 1]
    return None


def get_previous_version_dir() -> Path | None:
    """Public wrapper for callers outside the worker package (e.g. routers)."""
    return _previous_version_dir()


def _swap_active_symlink(target_dir: Path) -> None:
    """Atomically swap the 'active' symlink to point at target_dir."""
    tmp_link = VENV_BASE / "active.tmp"
    if tmp_link.is_symlink() or tmp_link.exists():
        tmp_link.unlink()
    tmp_link.symlink_to(target_dir.name)
    tmp_link.rename(VENV_ACTIVE)  # atomic on same filesystem


@asynccontextmanager
async def _exclusive_venv_lock():
    """Block gallery-dl starts while swapping or deleting venv directories."""
    VENV_BASE.mkdir(parents=True, exist_ok=True)
    lock_file = (VENV_BASE / ".lifecycle.lock").open("a+b")
    try:
        await asyncio.to_thread(fcntl.flock, lock_file.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()


async def _check_active_downloads() -> int:
    """Return count of jobs that can use or start the active gallery-dl venv."""
    from sqlalchemy import func, select

    from core.database import AsyncSessionLocal
    from db.models import DownloadJob

    async with AsyncSessionLocal() as session:
        return (
            await session.execute(
                select(func.count())
                .select_from(DownloadJob)
                .where(DownloadJob.status.in_(_ACTIVE_DOWNLOAD_STATUSES))
            )
        ).scalar_one()


async def _get_version(gdl_bin: str) -> str | None:
    """Run gallery-dl --version and return the version string."""
    try:
        rc, stdout, _ = await _run([gdl_bin, "--version"], timeout=10)
        if rc == 0 and stdout.strip():
            return stdout.strip()
    except Exception:
        pass
    return None


async def ensure_venv() -> None:
    """Ensure the venv exists and the 'active' symlink is valid.

    Called during worker startup. Creates v1 venv if nothing exists.
    """
    # Check if active symlink exists and points to valid venv
    if VENV_ACTIVE.is_symlink():
        target = VENV_ACTIVE.resolve()
        if target.exists() and (target / "bin" / "gallery-dl").exists():
            ver = await _get_version(str(target / "bin" / "gallery-dl"))
            if ver:
                logger.info("[gallery-dl venv] Active venv OK: %s → %s (v%s)", VENV_ACTIVE, target.name, ver)
                return
            logger.warning("[gallery-dl venv] Active venv has gallery-dl binary but version check failed; recreating")
        else:
            logger.warning("[gallery-dl venv] Active venv is missing gallery-dl binary; recreating")

    # Need to create initial venv
    VENV_BASE.mkdir(parents=True, exist_ok=True)
    v1 = VENV_BASE / "v1"
    if v1.exists():
        await asyncio.to_thread(shutil.rmtree, v1)

    logger.info("[gallery-dl venv] Creating initial venv at %s", v1)
    rc, _, stderr = await _run(
        _venv_create_cmd(v1),
        timeout=30,
    )
    if rc != 0:
        logger.error("[gallery-dl venv] venv creation failed: %s", stderr)
        raise RuntimeError(f"Failed to create venv: {stderr}")

    # Install gallery-dl (pinned baseline). This is a freshly created venv, so
    # its pip console script carries a correct self-referential shebang.
    pip_bin = str(v1 / "bin" / "pip")
    logger.info("[gallery-dl venv] Installing gallery-dl==%s into %s", INITIAL_GDL_VERSION, v1)
    rc, _, stderr = await _run(
        [pip_bin, "install", "--upgrade", f"gallery-dl=={INITIAL_GDL_VERSION}", "psycopg[binary]"],
        timeout=120,
    )
    if rc != 0:
        logger.error("[gallery-dl venv] pip install failed: %s", stderr)
        await asyncio.to_thread(shutil.rmtree, v1, True)
        raise RuntimeError(f"pip install gallery-dl failed: {stderr}")

    # Create symlink
    if VENV_ACTIVE.is_symlink() or VENV_ACTIVE.exists():
        VENV_ACTIVE.unlink()
    VENV_ACTIVE.symlink_to(v1.name)

    ver = await _get_version(str(v1 / "bin" / "gallery-dl"))
    logger.info("[gallery-dl venv] Initial venv ready: gallery-dl %s", ver)
    invalidate_gdl_bin_cache()


async def get_current_version() -> str | None:
    """Return the currently active gallery-dl version.

    Reads the version directly from the active venv's ``dist-info`` metadata
    rather than executing the binary.  This avoids a cross-process pitfall:
    ``_gdl_bin_cache`` is per-process, so the API process never sees the cache
    invalidation the worker performs after an upgrade — reading metadata is
    always accurate regardless of which process asks.

    Falls back to running the system ``gallery-dl --version`` if the venv
    does not exist.
    """
    if VENV_ACTIVE.exists():
        try:
            site_pkgs = VENV_ACTIVE / "lib"
            # Find gallery_dl-*.dist-info/METADATA
            for meta in site_pkgs.rglob("gallery_dl-*.dist-info/METADATA"):
                for line in meta.read_text().splitlines():
                    if line.startswith("Version:"):
                        return line.split(":", 1)[1].strip()
                break
        except Exception:
            pass
    # Fallback: system gallery-dl (e.g. baked into Docker image)
    return await _get_version("gallery-dl")


async def get_latest_pypi_version() -> str | None:
    """Fetch the latest gallery-dl version from PyPI."""
    try:
        import httpx

        async with httpx.AsyncClient() as client:
            resp = await client.get("https://pypi.org/pypi/gallery-dl/json", timeout=5)
            if resp.status_code == 200:
                return resp.json()["info"]["version"]
    except Exception as exc:
        logger.warning("[gallery-dl venv] Failed to fetch PyPI version: %s", exc)
    return None


async def _cleanup_new_dir(new_dir: Path) -> None:
    """Remove a failed upgrade directory."""
    await asyncio.to_thread(shutil.rmtree, new_dir, True)


async def _fail(status: str, error: str, requested_version: str | None = None) -> dict:
    """Emit a failure event and return the SAQ job result dict.

    Emitting on every failure/rejection (not just success) is what lets the
    admin UI surface the outcome instead of silently keeping the old version.
    """
    from core.events import EventType, emit_safe

    await emit_safe(
        EventType.SYSTEM_GDL_UPGRADE_FAILED,
        resource_type="gallery_dl",
        status=status,
        error=error,
        requested_version=requested_version,
    )
    return {"status": status, "error": error}


async def upgrade_job(ctx: dict, version: str | None = None) -> dict:  # noqa: ARG001
    """SAQ job: upgrade gallery-dl to a specific version (or latest).

    Steps:
    1. Check no downloads are queued, paused, or running
    2. Create a fresh, isolated venv dir (never clone the current one)
    3. pip install gallery-dl==version (or latest)
    4. Verify with --version
    5. Atomic symlink swap
    6. Clean up old versions (keep current + previous only)
    """
    from core.events import EventType, emit_safe

    # Reject before doing expensive installation work. The same check is
    # repeated under the exclusive lifecycle lock immediately before swap.
    active = await _check_active_downloads()
    if active > 0:
        return await _fail("rejected", f"{active} download(s) queued, paused, or running", version)

    old_version = await get_current_version()

    # 2. Create a fresh venv directory.
    #    NEVER shutil.copytree the current venv: venv entry-point scripts (pip,
    #    gallery-dl) embed an absolute-path shebang pointing at the SOURCE dir.
    #    Cloning leaves those shebangs dangling — the cloned pip installs into
    #    the wrong dir, and the cloned gallery-dl breaks the moment
    #    _cleanup_old_versions() removes the source dir (silent: get_current_
    #    version() reads dist-info without executing the binary).
    new_dir = _next_version_dir()
    logger.info("[gallery-dl venv] Upgrading: creating %s", new_dir)

    try:
        rc, _, stderr = await _run(_venv_create_cmd(new_dir), timeout=30)
        if rc != 0:
            await _cleanup_new_dir(new_dir)
            return await _fail("failed", f"venv creation failed: {stderr}", version)

        # 3. pip install — invoke pip via the new venv's own python so the
        #    install always targets new_dir, independent of any shebang.
        py_bin = str(new_dir / "bin" / "python")
        pkg = f"gallery-dl=={version}" if version else "gallery-dl"
        logger.info("[gallery-dl venv] Installing %s", pkg)
        rc, _, stderr = await _run([py_bin, "-m", "pip", "install", "--upgrade", pkg, "psycopg[binary]"], timeout=120)
        if rc != 0:
            await _cleanup_new_dir(new_dir)
            return await _fail("failed", f"pip install failed: {stderr}", version)

        # 4. Verify
        new_bin = str(new_dir / "bin" / "gallery-dl")
        new_version = await _get_version(new_bin)
        if not new_version:
            await _cleanup_new_dir(new_dir)
            return await _fail("failed", "gallery-dl --version failed after install", version)
    except Exception:
        await _cleanup_new_dir(new_dir)
        raise

    if version and new_version != version:
        logger.warning("[gallery-dl venv] Requested %s but got %s", version, new_version)

    # 5-6. Serialize the final guard, swap, and cleanup against every
    # gallery-dl subprocess. A download that starts after the first DB check
    # either holds the shared lock until it exits or waits and starts from the
    # new active venv after this block completes.
    async with _exclusive_venv_lock():
        active = await _check_active_downloads()
        if active > 0:
            await _cleanup_new_dir(new_dir)
            return await _fail("rejected", f"{active} download(s) queued, paused, or running", version)

        _swap_active_symlink(new_dir)
        logger.info("[gallery-dl venv] Upgraded: %s → %s", old_version, new_version)
        await _cleanup_old_versions()

    invalidate_gdl_bin_cache()

    await emit_safe(
        EventType.SYSTEM_GDL_UPGRADED,
        resource_type="gallery_dl",
        old_version=old_version,
        new_version=new_version,
    )

    return {
        "status": "ok",
        "old_version": old_version,
        "new_version": new_version,
    }


async def rollback_job(ctx: dict) -> dict:  # noqa: ARG001
    """SAQ job: rollback gallery-dl to the previous version."""
    from core.events import EventType, emit_safe

    async with _exclusive_venv_lock():
        active = await _check_active_downloads()
        if active > 0:
            return await _fail("rejected", f"{active} download(s) queued, paused, or running")

        prev_dir = _previous_version_dir()
        if prev_dir is None:
            return await _fail("failed", "No previous version to rollback to")

        if not (prev_dir / "bin" / "gallery-dl").exists():
            return await _fail("failed", f"Previous version {prev_dir.name} is corrupt")

        old_version = await get_current_version()
        current_dir = _current_version_dir()
        _swap_active_symlink(prev_dir)

        new_version = await _get_version(str(prev_dir / "bin" / "gallery-dl"))
        logger.info("[gallery-dl venv] Rolled back: %s → %s", old_version, new_version)

        # The exclusive lock proves no gallery-dl process can still import
        # from the version being removed.
        if current_dir and current_dir != prev_dir:
            await asyncio.to_thread(shutil.rmtree, current_dir, True)

    invalidate_gdl_bin_cache()

    await emit_safe(
        EventType.SYSTEM_GDL_UPGRADED,
        resource_type="gallery_dl",
        old_version=old_version,
        new_version=new_version,
        rollback=True,
    )

    return {
        "status": "ok",
        "old_version": old_version,
        "new_version": new_version,
    }


async def _cleanup_old_versions() -> None:
    """Remove all version dirs except current and one most recent other."""
    current = _current_version_dir()
    if current is None:
        return

    existing = _version_dirs()
    resolved = {d: d.resolve() for d in existing}

    # Always keep current; also keep the most recent non-current
    to_keep: set[Path] = {current}
    for d in reversed(existing):
        if resolved[d] != current:
            to_keep.add(resolved[d])
            break

    for d in existing:
        if resolved[d] not in to_keep:
            logger.info("[gallery-dl venv] Cleaning up old version: %s", d)
            await asyncio.to_thread(shutil.rmtree, d, True)
