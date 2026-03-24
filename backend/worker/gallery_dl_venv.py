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
import logging
import re
import shutil
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

VENV_BASE = Path("/opt/gallery-dl")
VENV_ACTIVE = VENV_BASE / "active"
GDL_BIN = VENV_ACTIVE / "bin" / "gallery-dl"

_VERSION_DIR_RE = re.compile(r"^v\d+$")

_gdl_bin_cache: str | None = None

def get_gdl_bin() -> str:
    """Return gallery-dl binary path — venv if available, else system PATH fallback."""
    global _gdl_bin_cache
    if _gdl_bin_cache is None:
        _gdl_bin_cache = str(GDL_BIN) if GDL_BIN.exists() else "gallery-dl"
    return _gdl_bin_cache

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

def _swap_active_symlink(target_dir: Path) -> None:
    """Atomically swap the 'active' symlink to point at target_dir."""
    tmp_link = VENV_BASE / "active.tmp"
    if tmp_link.is_symlink() or tmp_link.exists():
        tmp_link.unlink()
    tmp_link.symlink_to(target_dir.name)
    tmp_link.rename(VENV_ACTIVE)  # atomic on same filesystem

async def _check_running_downloads() -> int:
    """Return count of currently running download jobs."""
    from sqlalchemy import func, select

    from core.database import AsyncSessionLocal
    from db.models import DownloadJob

    async with AsyncSessionLocal() as session:
        return (
            await session.execute(select(func.count()).select_from(DownloadJob).where(DownloadJob.status == "running"))
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
            logger.info("[gallery-dl venv] Active venv OK: %s → %s (v%s)", VENV_ACTIVE, target.name, ver)
            return

    # Need to create initial venv
    VENV_BASE.mkdir(parents=True, exist_ok=True)
    v1 = VENV_BASE / "v1"
    if v1.exists():
        await asyncio.to_thread(shutil.rmtree, v1)

    logger.info("[gallery-dl venv] Creating initial venv at %s", v1)
    rc, _, stderr = await _run(
        [sys.executable, "-m", "venv", str(v1), "--system-site-packages"],
        timeout=30,
    )
    if rc != 0:
        logger.error("[gallery-dl venv] venv creation failed: %s", stderr)
        raise RuntimeError(f"Failed to create venv: {stderr}")

    # Install gallery-dl
    pip_bin = str(v1 / "bin" / "pip")
    logger.info("[gallery-dl venv] Installing gallery-dl into %s", v1)
    rc, _, stderr = await _run([pip_bin, "install", "gallery-dl", "psycopg[binary]"], timeout=120)
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

    Reads version directly from the active venv's package metadata via
    ``pip show``.  This avoids two cross-process pitfalls:

    * ``_gdl_bin_cache`` is per-process — the API process never sees the
      cache invalidation that the worker process performs after an upgrade.
    * The gallery-dl entry-point script's shebang may point to a stale
      Python path when the venv is a copytree of an older directory.

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

async def upgrade_job(ctx: dict, version: str | None = None) -> dict:  # noqa: ARG001
    """SAQ job: upgrade gallery-dl to a specific version (or latest).

    Steps:
    1. Check no downloads are running
    2. Create new venv dir (copytree from current)
    3. pip install gallery-dl==version (or latest)
    4. Verify with --version
    5. Atomic symlink swap
    6. Clean up old versions (keep current + previous only)
    """
    from core.events import EventType, emit_safe

    # 1. Check for running downloads
    running = await _check_running_downloads()
    if running > 0:
        return {"status": "rejected", "error": f"{running} download(s) still running"}

    current_dir = _current_version_dir()
    old_version = await get_current_version()

    # 2. Create new venv directory
    new_dir = _next_version_dir()
    logger.info("[gallery-dl venv] Upgrading: creating %s", new_dir)

    try:
        if current_dir:
            await asyncio.to_thread(shutil.copytree, current_dir, new_dir, symlinks=True)
        else:
            rc, _, stderr = await _run(
                [sys.executable, "-m", "venv", str(new_dir), "--system-site-packages"],
                timeout=30,
            )
            if rc != 0:
                await _cleanup_new_dir(new_dir)
                return {"status": "failed", "error": f"venv creation failed: {stderr}"}

        # 3. pip install
        pip_bin = str(new_dir / "bin" / "pip")
        pkg = f"gallery-dl=={version}" if version else "gallery-dl"
        logger.info("[gallery-dl venv] Installing %s", pkg)
        rc, _, stderr = await _run([pip_bin, "install", "--upgrade", pkg, "psycopg[binary]"], timeout=120)
        if rc != 0:
            await _cleanup_new_dir(new_dir)
            return {"status": "failed", "error": f"pip install failed: {stderr}"}

        # 4. Verify
        new_bin = str(new_dir / "bin" / "gallery-dl")
        new_version = await _get_version(new_bin)
        if not new_version:
            await _cleanup_new_dir(new_dir)
            return {"status": "failed", "error": "gallery-dl --version failed after install"}
    except Exception:
        await _cleanup_new_dir(new_dir)
        raise

    if version and new_version != version:
        logger.warning("[gallery-dl venv] Requested %s but got %s", version, new_version)

    # 5. Atomic symlink swap
    _swap_active_symlink(new_dir)

    logger.info("[gallery-dl venv] Upgraded: %s → %s", old_version, new_version)

    # 6. Cleanup: keep only current and previous
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

    # Check for running downloads
    running = await _check_running_downloads()
    if running > 0:
        return {"status": "rejected", "error": f"{running} download(s) still running"}

    prev_dir = _previous_version_dir()
    if prev_dir is None:
        return {"status": "failed", "error": "No previous version to rollback to"}

    if not (prev_dir / "bin" / "gallery-dl").exists():
        return {"status": "failed", "error": f"Previous version {prev_dir.name} is corrupt"}

    old_version = await get_current_version()
    current_dir = _current_version_dir()

    # Atomic symlink swap
    _swap_active_symlink(prev_dir)

    new_version = await _get_version(str(prev_dir / "bin" / "gallery-dl"))
    logger.info("[gallery-dl venv] Rolled back: %s → %s", old_version, new_version)

    # Remove the version we rolled back FROM
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
