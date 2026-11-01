"""backend/entrypoint.sh, run for real with its system commands replaced by recording stubs."""

import os
import subprocess
from pathlib import Path

import pytest

ENTRYPOINT = Path(__file__).parents[1] / "entrypoint.sh"

# `id -g <group name>` fails on a real system: id only takes user names.
ID_STUB = """#!/bin/sh
case "$1 $2" in
  "-u appuser"|"-g appuser") echo 1042 ;;
  *) echo "id: '$2': no such user" >&2; exit 1 ;;
esac
"""


@pytest.fixture
def run_entrypoint(tmp_path):
    log = tmp_path / "calls.log"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("groupmod", "usermod", "chown", "chmod", "mkdir", "gosu"):
        stub = bin_dir / name
        stub.write_text(f'#!/bin/sh\necho "{name} $*" >> "{log}"\n')
        stub.chmod(0o755)
    id_stub = bin_dir / "id"
    id_stub.write_text(ID_STUB)
    id_stub.chmod(0o755)

    def run(puid: str, pgid: str) -> tuple[list[str], str]:
        env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "PUID": puid, "PGID": pgid}
        done = subprocess.run(["/bin/sh", str(ENTRYPOINT), "true"], env=env, capture_output=True, text=True, check=True)
        return log.read_text().splitlines(), done.stderr

    return run


def test_entrypoint_default_identity_does_not_reown_the_image(run_entrypoint):
    calls, stderr = run_entrypoint("1042", "1042")

    assert "no such user" not in stderr
    assert not any(call.startswith(("groupmod", "usermod")) for call in calls)
    assert not any(call.startswith("chown -R") and " /app " in call for call in calls), (
        "a recursive chown copies the image into the container layer"
    )


def test_entrypoint_custom_identity_reowns_the_image(run_entrypoint):
    calls, _ = run_entrypoint("3000", "3000")

    assert "groupmod -g 3000 appgroup" in calls
    assert "usermod -u 3000 -g 3000 appuser" in calls
    assert "chown -R 3000:3000 /app /home/appuser" in calls


def test_entrypoint_custom_group_alone_reowns_the_image(run_entrypoint):
    calls, _ = run_entrypoint("1042", "3000")

    assert "groupmod -g 3000 appgroup" in calls


@pytest.mark.parametrize("identity", ["1042", "3000"])
def test_entrypoint_always_owns_the_gallery_dl_config_bind_mount(run_entrypoint, identity):
    """A fresh clone leaves ./config/gallery-dl owned by the host user, whatever PUID is."""
    calls, _ = run_entrypoint(identity, identity)

    assert f"chown -R {identity}:{identity} /home/appuser/.config/gallery-dl" in calls
