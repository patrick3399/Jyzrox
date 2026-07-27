"""Tests for worker/gallery_dl_venv.py — version detection logic.

Regression tests covering:
- get_current_version() reads from dist-info METADATA in the active venv,
  so the API process always sees the version installed in the active venv even
  after the worker has upgraded gallery-dl in a different process.
- get_current_version() never calls get_gdl_bin(), preventing stale-cache
  cross-process bugs.
- Fallback to system gallery-dl when venv does not exist.
- Fallback to system gallery-dl when METADATA is missing or unreadable.
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_dist_info(site_packages: Path, version: str) -> None:
    """Create a minimal gallery_dl-{version}.dist-info/METADATA file."""
    dist_info = site_packages / f"gallery_dl-{version}.dist-info"
    dist_info.mkdir(parents=True)
    (dist_info / "METADATA").write_text(
        f"Metadata-Version: 2.1\n"
        f"Name: gallery-dl\n"
        f"Version: {version}\n"
        f"Summary: Command-line program to download image-galleries\n"
    )


def test_get_gdl_exec_cmd_uses_shared_lifecycle_launcher(tmp_path):
    """Every gallery-dl subprocess command must enter through the lock holder."""
    from worker import gallery_dl_venv as venv_mod

    with (
        patch.object(venv_mod, "VENV_BASE", tmp_path),
        patch.object(venv_mod, "get_gdl_bin", return_value="/opt/gallery-dl/active/bin/gallery-dl"),
    ):
        command = venv_mod.get_gdl_exec_cmd()

    assert command == [
        sys.executable,
        "-m",
        "gallery_dl_exec",
        str(tmp_path / ".lifecycle.lock"),
        "/opt/gallery-dl/active/bin/gallery-dl",
    ]


@pytest.mark.asyncio
async def test_active_download_guard_covers_queued_paused_and_running():
    """The lifecycle guard must query every status that can retain/start a venv."""
    from worker import gallery_dl_venv as venv_mod

    result = MagicMock()
    result.scalar_one.return_value = 3
    session = AsyncMock()
    session.execute.return_value = result
    session_cm = AsyncMock()
    session_cm.__aenter__.return_value = session
    session_cm.__aexit__.return_value = False

    with patch("core.database.AsyncSessionLocal", return_value=session_cm):
        count = await venv_mod._check_active_downloads()

    statement = session.execute.await_args.args[0]
    params = statement.compile().params
    statuses = next(value for value in params.values() if isinstance(value, (list, tuple)))
    assert set(statuses) == {"queued", "paused", "running"}
    assert count == 3


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_current_version_reads_from_dist_info(tmp_path):
    """get_current_version() reads from dist-info METADATA, not subprocess."""
    from worker import gallery_dl_venv as venv_mod

    fake_active = tmp_path / "active"
    site_pkgs = fake_active / "lib" / "python3.13" / "site-packages"
    _create_dist_info(site_pkgs, "1.31.10")

    with (
        patch.object(venv_mod, "VENV_ACTIVE", fake_active),
        patch.object(venv_mod, "get_gdl_bin", side_effect=AssertionError("get_gdl_bin must not be called")),
    ):
        version = await venv_mod.get_current_version()

    assert version == "1.31.10"


@pytest.mark.asyncio
async def test_get_current_version_fallback_when_venv_missing():
    """When venv does not exist, fall back to system gallery-dl binary."""
    from worker import gallery_dl_venv as venv_mod

    fake_active = Path("/nonexistent/gallery-dl/active")

    async def fake_run(cmd, timeout=300):
        assert cmd == ["gallery-dl", "--version"]
        return (0, "1.28.0\n", "")

    with (
        patch.object(venv_mod, "VENV_ACTIVE", fake_active),
        patch.object(venv_mod, "_run", side_effect=fake_run),
    ):
        version = await venv_mod.get_current_version()

    assert version == "1.28.0"


@pytest.mark.asyncio
async def test_get_current_version_fallback_when_no_dist_info(tmp_path):
    """When dist-info is missing, fall back to system gallery-dl binary."""
    from worker import gallery_dl_venv as venv_mod

    fake_active = tmp_path / "active"
    (fake_active / "lib").mkdir(parents=True)  # exists but no dist-info

    async def fake_run(cmd, timeout=300):
        return (0, "1.28.0\n", "")

    with (
        patch.object(venv_mod, "VENV_ACTIVE", fake_active),
        patch.object(venv_mod, "_run", side_effect=fake_run),
    ):
        version = await venv_mod.get_current_version()

    assert version == "1.28.0"


@pytest.mark.asyncio
async def test_get_current_version_fallback_when_metadata_unreadable(tmp_path):
    """When METADATA file is unreadable, fall back gracefully."""
    from worker import gallery_dl_venv as venv_mod

    fake_active = tmp_path / "active"
    site_pkgs = fake_active / "lib" / "python3.13" / "site-packages"
    dist_info = site_pkgs / "gallery_dl-1.31.10.dist-info"
    dist_info.mkdir(parents=True)
    # Create METADATA as a directory (will cause read_text() to fail)
    (dist_info / "METADATA").mkdir()

    async def fake_run(cmd, timeout=300):
        return (0, "1.28.0\n", "")

    with (
        patch.object(venv_mod, "VENV_ACTIVE", fake_active),
        patch.object(venv_mod, "_run", side_effect=fake_run),
    ):
        version = await venv_mod.get_current_version()

    assert version == "1.28.0"


@pytest.mark.asyncio
async def test_get_current_version_parses_version_line_only(tmp_path):
    """Only the 'Version:' line from METADATA is used."""
    from worker import gallery_dl_venv as venv_mod

    fake_active = tmp_path / "active"
    site_pkgs = fake_active / "lib" / "python3.13" / "site-packages"
    _create_dist_info(site_pkgs, "1.29.3")

    with patch.object(venv_mod, "VENV_ACTIVE", fake_active):
        version = await venv_mod.get_current_version()

    assert version == "1.29.3"


@pytest.mark.asyncio
async def test_ensure_venv_creates_isolated_venv(tmp_path):
    """Initial venv creation must not inherit system gallery-dl packages."""
    from worker import gallery_dl_venv as venv_mod

    fake_base = tmp_path / "gallery-dl"
    fake_active = fake_base / "active"
    calls: list[list[str]] = []

    async def fake_run(cmd, timeout=300):
        calls.append(cmd)
        if cmd[:3] == [str(fake_base / "v1" / "bin" / "pip"), "install", "--upgrade"]:
            return (0, "", "")
        if cmd == [str(fake_base / "v1" / "bin" / "gallery-dl"), "--version"]:
            return (0, "1.32.1\n", "")
        return (0, "", "")

    with (
        patch.object(venv_mod, "VENV_BASE", fake_base),
        patch.object(venv_mod, "VENV_ACTIVE", fake_active),
        patch.object(venv_mod, "_run", side_effect=fake_run),
    ):
        await venv_mod.ensure_venv()

    assert calls[0] == [venv_mod.sys.executable, "-m", "venv", str(fake_base / "v1")]
    assert "--system-site-packages" not in calls[0]
    assert fake_active.is_symlink()
    assert fake_active.readlink() == Path("v1")


@pytest.mark.asyncio
async def test_ensure_venv_recreates_active_without_gallery_dl_binary(tmp_path):
    """A venv that only sees system gallery-dl is treated as corrupt."""
    from worker import gallery_dl_venv as venv_mod

    fake_base = tmp_path / "gallery-dl"
    v1 = fake_base / "v1"
    v1.mkdir(parents=True)
    fake_active = fake_base / "active"
    fake_active.symlink_to("v1")
    calls: list[list[str]] = []

    async def fake_run(cmd, timeout=300):
        calls.append(cmd)
        if cmd[:3] == [str(v1 / "bin" / "pip"), "install", "--upgrade"]:
            return (0, "", "")
        if cmd == [str(v1 / "bin" / "gallery-dl"), "--version"]:
            return (0, "1.32.1\n", "")
        return (0, "", "")

    with (
        patch.object(venv_mod, "VENV_BASE", fake_base),
        patch.object(venv_mod, "VENV_ACTIVE", fake_active),
        patch.object(venv_mod, "_run", side_effect=fake_run),
    ):
        await venv_mod.ensure_venv()

    assert calls[0] == [venv_mod.sys.executable, "-m", "venv", str(v1)]
    assert "--system-site-packages" not in calls[0]


# ---------------------------------------------------------------------------
# Regression: upgrade must build a fresh venv, never clone (stale-shebang bug)
# ---------------------------------------------------------------------------


def _make_fake_venv(target: Path, version: str) -> None:
    """Fabricate a minimal venv whose entry-point scripts carry a shebang
    pointing at *their own* interpreter — mimicking what ``python -m venv`` +
    pip produce for a fresh venv.
    """
    bindir = target / "bin"
    bindir.mkdir(parents=True, exist_ok=True)
    (bindir / "python").write_text("")  # stand-in interpreter
    for script in ("gallery-dl", "pip"):
        (bindir / script).write_text(f"#!{bindir / 'python'}\n")
    _create_dist_info(target / "lib" / "python3.14" / "site-packages", version)


@pytest.mark.asyncio
async def test_upgrade_does_not_clone_venv_so_active_entrypoint_survives_cleanup(tmp_path):
    """Two upgrades + cleanup must leave the active gallery-dl runnable.

    Regression for the copytree bug: cloning a venv copies entry-point scripts
    whose shebang is an absolute path to the SOURCE venv dir. Once
    ``_cleanup_old_versions()`` deletes that source dir (keeps only current +
    one previous), every cloned gallery-dl script points at a missing
    interpreter and gallery-dl stops working — silently, because
    ``get_current_version()`` reads dist-info without executing the binary.
    """
    from worker import gallery_dl_venv as venv_mod

    fake_base = tmp_path / "gallery-dl"
    fake_active = fake_base / "active"

    # Initial v1 venv (correct self-referential shebang) + active -> v1.
    _make_fake_venv(fake_base / "v1", "1.32.1")
    fake_active.symlink_to("v1")

    async def fake_run(cmd, timeout=300):
        # python -m venv <target>: fabricate a fresh, self-consistent venv.
        if cmd[1:3] == ["-m", "venv"]:
            _make_fake_venv(Path(cmd[3]), "1.32.6")
            return (0, "", "")
        if "--version" in cmd:
            return (0, "1.32.6\n", "")
        return (0, "", "")  # pip install etc.

    with (
        patch.object(venv_mod, "VENV_BASE", fake_base),
        patch.object(venv_mod, "VENV_ACTIVE", fake_active),
        patch.object(venv_mod, "_run", side_effect=fake_run),
        patch.object(venv_mod, "_check_active_downloads", new_callable=AsyncMock, return_value=0),
        patch("core.events.emit_safe", new_callable=AsyncMock),
    ):
        r1 = await venv_mod.upgrade_job({})
        r2 = await venv_mod.upgrade_job({})

    assert r1["status"] == "ok"
    assert r2["status"] == "ok"

    # v1 has been cleaned up (only current + one previous are kept).
    assert not (fake_base / "v1").exists()

    # The active gallery-dl entry script's shebang must point at an interpreter
    # that still exists — otherwise gallery-dl is silently unrunnable.
    shebang = (fake_active / "bin" / "gallery-dl").read_text().splitlines()[0]
    assert shebang.startswith("#!")
    interpreter = Path(shebang[2:].strip())
    assert interpreter.exists(), f"active gallery-dl shebang points at missing interpreter: {interpreter}"


# ---------------------------------------------------------------------------
# Regression: upgrade failures must emit an event (no longer silent)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upgrade_job_install_failure_emits_upgrade_failed_event(tmp_path):
    """A failed upgrade must emit SYSTEM_GDL_UPGRADE_FAILED so the UI can react.

    Previously upgrade_job returned {"status": "failed"} without emitting any
    event, leaving the admin UI with no signal — the panel just silently kept
    the old version.
    """
    from core.events import EventType
    from worker import gallery_dl_venv as venv_mod

    fake_base = tmp_path / "gallery-dl"
    fake_active = fake_base / "active"
    _make_fake_venv(fake_base / "v1", "1.32.1")
    fake_active.symlink_to("v1")

    async def fake_run(cmd, timeout=300):
        if cmd[1:3] == ["-m", "venv"]:
            _make_fake_venv(Path(cmd[3]), "1.32.1")
            return (0, "", "")
        if "install" in cmd:
            return (1, "", "network unreachable")  # pip install fails
        if "--version" in cmd:
            return (0, "1.32.1\n", "")
        return (0, "", "")

    emit = AsyncMock()
    with (
        patch.object(venv_mod, "VENV_BASE", fake_base),
        patch.object(venv_mod, "VENV_ACTIVE", fake_active),
        patch.object(venv_mod, "_run", side_effect=fake_run),
        patch.object(venv_mod, "_check_active_downloads", new_callable=AsyncMock, return_value=0),
        patch("core.events.emit_safe", emit),
    ):
        result = await venv_mod.upgrade_job({}, version="1.99.0")

    assert result["status"] == "failed"
    assert emit.await_count == 1
    assert emit.await_args.args[0] == EventType.SYSTEM_GDL_UPGRADE_FAILED
    kwargs = emit.await_args.kwargs
    assert kwargs["status"] == "failed"
    assert "pip install failed" in kwargs["error"]
    assert kwargs["requested_version"] == "1.99.0"


@pytest.mark.asyncio
async def test_upgrade_job_rejected_when_downloads_active_emits_event(tmp_path):
    """A rejected upgrade (downloads active) must also emit a failure event,
    distinctly flagged as ``rejected`` so the UI can show an actionable reason.
    """
    from core.events import EventType
    from worker import gallery_dl_venv as venv_mod

    fake_base = tmp_path / "gallery-dl"
    fake_active = fake_base / "active"
    _make_fake_venv(fake_base / "v1", "1.32.1")
    fake_active.symlink_to("v1")

    emit = AsyncMock()
    with (
        patch.object(venv_mod, "VENV_BASE", fake_base),
        patch.object(venv_mod, "VENV_ACTIVE", fake_active),
        patch.object(venv_mod, "_check_active_downloads", new_callable=AsyncMock, return_value=3),
        patch("core.events.emit_safe", emit),
    ):
        result = await venv_mod.upgrade_job({})

    assert result["status"] == "rejected"
    assert emit.await_count == 1
    assert emit.await_args.args[0] == EventType.SYSTEM_GDL_UPGRADE_FAILED
    assert emit.await_args.kwargs["status"] == "rejected"
    assert "queued, paused, or running" in emit.await_args.kwargs["error"]


@pytest.mark.asyncio
async def test_upgrade_rechecks_active_downloads_before_swap(tmp_path):
    """A job becoming active during install rejects the swap and preserves v1."""
    from worker import gallery_dl_venv as venv_mod

    fake_base = tmp_path / "gallery-dl"
    fake_active = fake_base / "active"
    _make_fake_venv(fake_base / "v1", "1.32.1")
    fake_active.symlink_to("v1")

    async def fake_run(cmd, timeout=300):
        if cmd[1:3] == ["-m", "venv"]:
            _make_fake_venv(Path(cmd[3]), "1.32.8")
            return (0, "", "")
        if "--version" in cmd:
            return (0, "1.32.8\n", "")
        return (0, "", "")

    emit = AsyncMock()
    with (
        patch.object(venv_mod, "VENV_BASE", fake_base),
        patch.object(venv_mod, "VENV_ACTIVE", fake_active),
        patch.object(venv_mod, "_run", side_effect=fake_run),
        patch.object(venv_mod, "_check_active_downloads", new_callable=AsyncMock, side_effect=[0, 1]),
        patch("core.events.emit_safe", emit),
    ):
        result = await venv_mod.upgrade_job({}, version="1.32.8")

    assert result["status"] == "rejected"
    assert fake_active.resolve() == fake_base / "v1"
    assert not (fake_base / "v2").exists()
    assert emit.await_args.kwargs["status"] == "rejected"


@pytest.mark.asyncio
async def test_rollback_waits_for_gallery_dl_process_before_deleting_venv(tmp_path):
    """A process starting before rollback must retain its venv until exit."""
    from worker import gallery_dl_venv as venv_mod

    fake_base = tmp_path / "gallery-dl"
    fake_active = fake_base / "active"
    _make_fake_venv(fake_base / "v1", "1.32.1")
    _make_fake_venv(fake_base / "v2", "1.32.8")
    fake_active.symlink_to("v2")
    started = tmp_path / "started"
    release = tmp_path / "release"
    child_code = f"""\
import pathlib
import time

pathlib.Path({str(started)!r}).touch()
release = pathlib.Path({str(release)!r})
deadline = time.monotonic() + 5
while not release.exists() and time.monotonic() < deadline:
    time.sleep(0.01)
"""

    with (
        patch.object(venv_mod, "VENV_BASE", fake_base),
        patch.object(venv_mod, "VENV_ACTIVE", fake_active),
        patch.object(venv_mod, "_check_active_downloads", new_callable=AsyncMock, return_value=0),
        patch("core.events.emit_safe", new_callable=AsyncMock),
    ):
        cmd = [
            sys.executable,
            "-m",
            "gallery_dl_exec",
            str(fake_base / ".lifecycle.lock"),
            sys.executable,
            "-c",
            child_code,
        ]
        proc = await asyncio.create_subprocess_exec(*cmd)
        for _ in range(200):
            if started.exists():
                break
            await asyncio.sleep(0.01)
        assert started.exists()

        rollback = asyncio.create_task(venv_mod.rollback_job({}))
        await asyncio.sleep(0.05)
        assert not rollback.done()
        assert fake_active.resolve() == fake_base / "v2"
        assert (fake_base / "v2").exists()

        release.touch()
        assert await proc.wait() == 0
        result = await asyncio.wait_for(rollback, timeout=2)

    assert result["status"] == "ok"
    assert fake_active.resolve() == fake_base / "v1"
    assert not (fake_base / "v2").exists()


async def test_rollback_gives_up_instead_of_waiting_on_a_long_download(tmp_path):
    """A held shared lock must time out into `rejected`, not block forever.

    The DB precheck is a TOCTOU (a download can start right after it) and flock
    grants no priority to a waiting writer, so a plain blocking LOCK_EX could be
    starved indefinitely by a stream of downloads while pinning a worker slot.
    """
    from worker import gallery_dl_venv as venv_mod

    fake_base = tmp_path / "gdl"
    (fake_base / "v1" / "bin").mkdir(parents=True)
    (fake_base / "v1" / "bin" / "gallery-dl").write_text("#!/bin/sh\n")
    (fake_base / "v2" / "bin").mkdir(parents=True)
    fake_active = fake_base / "active"
    fake_active.symlink_to("v2")

    started = tmp_path / "started2"
    release = tmp_path / "release2"
    child_code = f"""\
import pathlib
import time

pathlib.Path({str(started)!r}).touch()
release = pathlib.Path({str(release)!r})
deadline = time.monotonic() + 10
while not release.exists() and time.monotonic() < deadline:
    time.sleep(0.01)
"""

    with (
        patch.object(venv_mod, "VENV_BASE", fake_base),
        patch.object(venv_mod, "VENV_ACTIVE", fake_active),
        patch.object(venv_mod, "_LIFECYCLE_LOCK_TIMEOUT", 0.3),
        patch.object(venv_mod, "_LIFECYCLE_LOCK_POLL", 0.05),
        patch.object(venv_mod, "_check_active_downloads", new_callable=AsyncMock, return_value=0),
        patch.object(venv_mod, "_fail", new_callable=AsyncMock, side_effect=lambda s, m, *a: {"status": s, "error": m}),
        patch("core.events.emit_safe", new_callable=AsyncMock),
    ):
        cmd = [
            sys.executable,
            "-m",
            "gallery_dl_exec",
            str(fake_base / ".lifecycle.lock"),
            sys.executable,
            "-c",
            child_code,
        ]
        proc = await asyncio.create_subprocess_exec(*cmd)
        for _ in range(400):
            if started.exists():
                break
            await asyncio.sleep(0.01)
        assert started.exists()

        # Must return on its own while the lock is still held.
        result = await asyncio.wait_for(venv_mod.rollback_job({}), timeout=5)

        release.touch()
        await proc.wait()

    assert result["status"] == "rejected"
    assert "still held" in result["error"]
    # Nothing was swapped or deleted while a gallery-dl process held the lock.
    assert fake_active.resolve() == fake_base / "v2"
    assert (fake_base / "v2").exists()
