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

from pathlib import Path
from unittest.mock import patch

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
