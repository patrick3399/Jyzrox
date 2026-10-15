"""Bundled custom gallery-dl extractors.

gallery-dl only discovers extractor modules outside its own package through the
``extractor.module-sources`` option, and that option is applied in its CLI entry
point (``gallery_dl.__init__.main``). Three independent consumers need to see
the same extractors:

* the **download subprocess**, which reads the config written by
  ``_build_gallery_dl_config()`` — covered by ``extractor_source_dirs()``;
* the **admin site probe** (``core.probe._run_gallery_dl_probe``), which runs
  with ``--config /dev/null`` to keep credentials out of probe runs and so
  never sees ``module-sources`` — passes ``extractor_source_dirs()`` on the CLI
  as ``-X/--extractors`` instead;
* the **in-process** ``gallery_dl.extractor`` import used for URL/category
  detection (``plugins.registry.detect_source``) and ``directory_fmt`` lookup
  (``._metadata._get_identity_field``). That code path never runs ``main()``,
  so ``module-sources`` does nothing for it — covered by ``load_inprocess()``.

All three read the same directory, so a bundled extractor can never be visible
to one consumer and invisible to another.

Note the two consumers do not even use the same gallery-dl installation: the
subprocess runs the upgradable venv at ``/opt/gallery-dl`` while the in-process
import resolves to the copy baked into the image. Extractors live under
``/app`` precisely so venv upgrade/rollback cannot take them away mid-job.
"""

import logging
import sys
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

_BUNDLED_DIR = Path(__file__).parent / "extractors"

# Modules already handed to gallery-dl's in-process registry. init_plugins()
# runs more than once per process (API startup, worker startup, worker
# re-init), and add_module() appends to gallery-dl's class cache without
# deduplicating — re-adding would stack duplicate patterns on every call.
_loaded: set[str] = set()


@lru_cache(maxsize=1)
def _module_names() -> tuple[str, ...]:
    """Return the importable module names in the bundled directory.

    Mirrors gallery-dl's own discovery rule (``*.py``, non-recursive) so the
    subprocess and the in-process loader agree on what counts as an extractor.
    """
    if not _BUNDLED_DIR.is_dir():
        return ()
    return tuple(sorted(p.stem for p in _BUNDLED_DIR.glob("*.py")))


def extractor_source_dirs() -> list[str]:
    """Directories to advertise via ``extractor.module-sources``.

    Empty when no extractor is bundled, so the generated config stays byte-for-
    byte identical to the pre-feature output until someone actually adds one.
    """
    return [str(_BUNDLED_DIR)] if _module_names() else []


def _register_declared_sites(name: str, module, classes) -> None:
    """Register the module's ``JYZROX_SITE`` declaration(s) in the site registry.

    Gives a drop-in extractor what a GDL_SITES entry gives a built-in one
    (display name, title/tags for gallery sites, metadata rules, credentials)
    without editing ``_sites.py``. A bad declaration only logs: the extractor
    itself stays loaded and the site behaves as unregistered.
    """
    declared = getattr(module, "JYZROX_SITE", None)
    if declared is None:
        return
    from plugins.builtin.gallery_dl._sites import register_site, site_config_from_declaration

    categories = {c for cls in classes if isinstance(c := getattr(cls, "category", None), str) and c}
    for declaration in declared if isinstance(declared, (list, tuple)) else (declared,):
        try:
            config, metadata_fields = site_config_from_declaration(declaration, categories)
        except Exception as exc:  # SiteDeclarationError, or anything odd the file put there
            logger.warning("[gallery_dl] ignoring JYZROX_SITE in custom extractor %r: %s", name, exc)
            continue
        if reason := register_site(config, metadata_fields):
            logger.warning("[gallery_dl] ignoring JYZROX_SITE in custom extractor %r: %s", name, reason)
            continue
        logger.info(
            "[gallery_dl] registered site %s (%s) from custom extractor %r", config.source_id, config.domain, name
        )


def load_inprocess() -> list[str]:
    """Register bundled extractors with the in-process ``gallery_dl.extractor``.

    Returns the module names newly registered by this call. A module's
    ``JYZROX_SITE`` declaration is registered in the site registry alongside.

    Never raises: this runs from ``init_plugins()``, which is on the startup
    path of both the API and the worker (and of the test suite's import-time
    bootstrap). A malformed extractor file, or a gallery-dl version whose API
    has moved, must degrade to "custom extractors are not detected in-process"
    rather than take the process down.
    """
    names = _module_names()
    if not names:
        return []

    try:
        from gallery_dl import extractor
    except ImportError as exc:
        # Expected wherever gallery-dl is not installed (e.g. local test runs).
        logger.debug("[gallery_dl] in-process extractor load skipped: %s", exc)
        return []

    loaded: list[str] = []
    path = str(_BUNDLED_DIR)
    for name in names:
        if name in _loaded:
            continue
        try:
            # gallery-dl imports these as top-level modules; do the same so a
            # module is not held twice under two names.
            sys.path.insert(0, path)
            try:
                module = __import__(name)
            finally:
                # Remove by identity, not index: an extractor's own imports may
                # have mutated sys.path while we were inside __import__.
                try:
                    sys.path.remove(path)
                except ValueError:
                    pass
            classes = extractor.add_module(module)
            if not classes:
                logger.warning(
                    "[gallery_dl] custom extractor %r defines no extractor classes",
                    name,
                )
                continue
        except Exception as exc:
            logger.warning("[gallery_dl] failed to load custom extractor %r: %s", name, exc)
            continue
        _loaded.add(name)
        loaded.append(name)
        _register_declared_sites(name, module, classes)

    if loaded:
        # directory_fmt lookups are memoised per category and may already have
        # cached a miss for a category these extractors provide.
        from plugins.builtin.gallery_dl._metadata import _get_identity_field

        _get_identity_field.cache_clear()
        logger.info("[gallery_dl] loaded custom extractors: %s", ", ".join(loaded))

    return loaded
