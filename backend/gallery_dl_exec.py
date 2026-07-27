"""Launch gallery-dl while holding a shared lock on its venv lifecycle."""

import fcntl
import os
import sys
from pathlib import Path


def main() -> None:
    """Acquire the shared lifecycle lock, then replace this process."""
    if len(sys.argv) < 3:
        raise SystemExit("usage: gallery_dl_exec LOCK_PATH COMMAND [ARG ...]")

    lock_path = Path(sys.argv[1])
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDONLY, 0o600)
    fcntl.flock(lock_fd, fcntl.LOCK_SH)
    os.set_inheritable(lock_fd, True)

    command = sys.argv[2:]
    os.execvp(command[0], command)  # noqa: S606 - internal argv, no shell


if __name__ == "__main__":
    main()
