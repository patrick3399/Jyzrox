"""Unified version detection for Jyzrox.

Resolution order:
1. APP_VERSION env var (set by Docker build-arg or CI)
2. git describe --tags --always (local dev)
3. "dev" fallback
"""

import os
import subprocess


def _detect_version() -> str:
    if v := os.environ.get("APP_VERSION"):
        return v
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--always"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if tag := result.stdout.strip():
            return tag
    except Exception:
        pass
    return "dev"


__version__ = _detect_version()
