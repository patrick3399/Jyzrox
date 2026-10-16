"""Environment for every gallery-dl subprocess Jyzrox starts.

``SITE_DIR`` holds a single ``sitecustomize.py`` that gives requests Happy
Eyeballs (see that file). Putting the directory first on ``PYTHONPATH`` makes
the interpreter import it at startup, under whichever gallery-dl venv is
active, without installing anything into the venv -- upgrade and rollback
replace the venv, while this directory ships with the app.
"""

import os
from collections.abc import Mapping
from pathlib import Path

SITE_DIR = Path(__file__).parent / "_subprocess_site"


def gdl_subprocess_env(base: Mapping[str, str] | None = None, **extra: str) -> dict[str, str]:
    """Return ``base`` (default: ``os.environ``) plus ``extra``, with SITE_DIR first on PYTHONPATH."""
    env = dict(os.environ if base is None else base)
    env.update(extra)
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = os.pathsep.join([str(SITE_DIR), existing]) if existing else str(SITE_DIR)
    return env
