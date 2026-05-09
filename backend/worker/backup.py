"""Database backup job for disaster recovery."""

import asyncio
import contextlib
import gzip
import hashlib
import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

from core.config import settings
from core.version import __version__
from worker.constants import logger
from worker.helpers import _cron_record, _cron_should_run

TASK_ID = "database_backup"
DEFAULT_CRON = "0 2 * * *"


def _backup_basename(now: datetime | None = None) -> str:
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%d_%H%M%S")
    return f"jyzrox_db_{stamp}"


def _pg_dump_connection() -> tuple[str, str | None]:
    """Return a password-free libpq URL and optional PGPASSWORD value."""
    url = settings.database_url.replace("+asyncpg", "")
    if not url.startswith(("postgresql://", "postgres://")):
        raise RuntimeError("Database backup requires a PostgreSQL DATABASE_URL")
    parsed = urlsplit(url)
    userinfo = ""
    if parsed.username:
        userinfo = quote(parsed.username)
        if parsed.hostname:
            userinfo += "@"
    host = parsed.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = f"{userinfo}{host}"
    if parsed.port:
        netloc += f":{parsed.port}"
    safe_url = urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))
    return safe_url, parsed.password


def _db_manifest_fields(url: str) -> dict[str, str | int | None]:
    parsed = urlsplit(url)
    return {
        "database": parsed.path.lstrip("/") or None,
        "host": parsed.hostname,
        "port": parsed.port,
        "username": parsed.username,
    }


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_manifest(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


async def _record_running(r) -> None:
    await r.set(f"cron:{TASK_ID}:last_run", datetime.now(UTC).isoformat())
    await r.set(f"cron:{TASK_ID}:last_status", "running")
    await r.delete(f"cron:{TASK_ID}:last_error")


def _successful_manifests(backup_dir: Path) -> list[tuple[Path, dict]]:
    manifests: list[tuple[Path, dict]] = []
    for path in backup_dir.glob("jyzrox_db_*.json"):
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("status") == "ok":
            manifests.append((path, data))
    return sorted(manifests, key=lambda item: str(item[1].get("created_at") or ""))


def _enforce_retention(backup_dir: Path) -> int:
    keep = max(1, settings.backup_retention_count)
    manifests = _successful_manifests(backup_dir)
    remove_count = max(0, len(manifests) - keep)
    removed = 0
    for manifest_path, data in manifests[:remove_count]:
        for filename in (data.get("filename"), manifest_path.name):
            if not filename:
                continue
            path = backup_dir / str(filename)
            try:
                if path.exists():
                    path.unlink()
                    removed += 1
            except OSError as exc:
                logger.warning("[backup] failed to delete old backup file %s: %s", path, exc)
    return removed


async def _run_pg_dump(out_path: Path) -> None:
    db_url, password = _pg_dump_connection()
    cmd = [
        "pg_dump",
        "--clean",
        "--if-exists",
        "--dbname",
        db_url,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "PGCONNECT_TIMEOUT": "30", **({"PGPASSWORD": password} if password else {})},
    )
    assert proc.stdout is not None
    assert proc.stderr is not None

    try:
        with gzip.open(out_path, "wb") as gz:
            while True:
                chunk = await proc.stdout.read(1024 * 1024)
                if not chunk:
                    break
                gz.write(chunk)
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=settings.backup_pg_dump_timeout)
    except Exception:
        proc.kill()
        with contextlib.suppress(Exception):
            await proc.wait()
        raise

    if proc.returncode != 0:
        message = stderr.decode(errors="replace").strip() or f"pg_dump exited with {proc.returncode}"
        raise RuntimeError(message)


async def database_backup_job(ctx: dict, force: bool = False) -> dict:
    """Create a compressed PostgreSQL dump and filesystem manifest."""
    r = ctx["redis"]
    if not force and not await _cron_should_run(ctx, TASK_ID, DEFAULT_CRON):
        logger.info("[backup] skipping — cron gate not reached")
        return {"status": "skipped", "reason": "interval_not_reached"}

    claim_key = "backup:database:claim"
    claimed = await r.set(claim_key, datetime.now(UTC).isoformat(), nx=True, ex=settings.backup_pg_dump_timeout + 300)
    if not claimed:
        return {"status": "already_running"}

    backup_dir = Path(settings.data_backups_path)
    backup_dir.mkdir(parents=True, exist_ok=True)

    basename = _backup_basename()
    final_path = backup_dir / f"{basename}.sql.gz"
    tmp_path = backup_dir / f"{basename}.sql.gz.tmp"
    manifest_path = backup_dir / f"{basename}.json"
    created_at = datetime.now(UTC).isoformat()
    await _record_running(r)

    try:
        await _run_pg_dump(tmp_path)
        tmp_path.replace(final_path)
        size_bytes = final_path.stat().st_size
        sha256 = await asyncio.to_thread(_sha256_file, final_path)
        db_url, _ = _pg_dump_connection()
        manifest = {
            "id": basename,
            "status": "ok",
            "created_at": created_at,
            "filename": final_path.name,
            "manifest": manifest_path.name,
            "size_bytes": size_bytes,
            "sha256": sha256,
            "app_version": os.environ.get("APP_VERSION", __version__),
            "pg_dump": shutil.which("pg_dump"),
            **_db_manifest_fields(db_url),
        }
        await asyncio.to_thread(_write_manifest, manifest_path, manifest)
        removed = await asyncio.to_thread(_enforce_retention, backup_dir)
        await _cron_record(ctx, TASK_ID, "ok")
        logger.info("[backup] created %s (%d bytes)", final_path, size_bytes)
        return {
            "status": "ok",
            "backup_id": basename,
            "filename": final_path.name,
            "size_bytes": size_bytes,
            "sha256": sha256,
            "removed_old_files": removed,
        }
    except Exception as exc:
        for path in (tmp_path, final_path):
            try:
                if path.exists():
                    path.unlink()
            except OSError:
                pass
        error = str(exc)
        manifest = {
            "id": basename,
            "status": "failed",
            "created_at": created_at,
            "filename": final_path.name,
            "manifest": manifest_path.name,
            "error": error,
            "app_version": os.environ.get("APP_VERSION", __version__),
        }
        await asyncio.to_thread(_write_manifest, manifest_path, manifest)
        await _cron_record(ctx, TASK_ID, "failed", error)
        logger.error("[backup] failed: %s", error)
        return {"status": "failed", "error": error}
    finally:
        await r.delete(claim_key, f"cron:{TASK_ID}:manual_claim")
