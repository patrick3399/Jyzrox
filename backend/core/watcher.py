"""Real-time library directory monitoring via watchdog."""

import asyncio
import logging
import threading
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

logger = logging.getLogger(__name__)

_SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".heic", ".mp4", ".webm"}


class _LibraryHandler(FileSystemEventHandler):
    """Debounced handler that enqueues ARQ jobs on file/dir changes."""

    def __init__(self, enqueue_fn, debounce_secs: int = 30):
        self._enqueue = enqueue_fn
        self._debounce_secs = debounce_secs
        self._pending: dict[str, threading.Timer] = {}
        self._lock = threading.Lock()
        self._paused = False

    def _schedule(self, key: str, job_name: str, *args):
        if self._paused:
            return
        with self._lock:
            existing = self._pending.pop(key, None)
            if existing:
                existing.cancel()
            t = threading.Timer(self._debounce_secs, self._fire, args=(key, job_name, *args))
            t.daemon = True
            self._pending[key] = t
            t.start()

    def _fire(self, key: str, job_name: str, *args):
        with self._lock:
            self._pending.pop(key, None)
        try:
            self._enqueue(job_name, *args)
        except Exception:
            logger.exception("[watcher] Failed to enqueue %s", job_name)

    def on_created(self, event):
        if event.is_directory:
            self._schedule("discover", "auto_discover_job")
        else:
            ext = Path(event.src_path).suffix.lower()
            if ext in _SUPPORTED_EXTS:
                parent = str(Path(event.src_path).parent)
                self._schedule(f"rescan:{parent}", "rescan_by_path_job", parent)

    def on_deleted(self, event):
        if not event.is_directory:
            parent = str(Path(event.src_path).parent)
            self._schedule(f"rescan:{parent}", "rescan_by_path_job", parent)

    def on_moved(self, event):
        if event.is_directory:
            self._schedule("discover", "auto_discover_job")
        else:
            ext = Path(event.dest_path).suffix.lower()
            old_parent = str(Path(event.src_path).parent)
            new_parent = str(Path(event.dest_path).parent)
            # Rescan both old and new parent directories
            self._schedule(f"rescan:{old_parent}", "rescan_by_path_job", old_parent)
            if new_parent != old_parent and ext in _SUPPORTED_EXTS:
                self._schedule(f"rescan:{new_parent}", "rescan_by_path_job", new_parent)

    def on_modified(self, event):
        # Only care about file modifications (e.g., image replaced in-place)
        if not event.is_directory:
            ext = Path(event.src_path).suffix.lower()
            if ext in _SUPPORTED_EXTS:
                parent = str(Path(event.src_path).parent)
                self._schedule(f"rescan:{parent}", "rescan_by_path_job", parent)


class LibraryWatcher:
    """Manages watchdog Observer for library directories."""

    def __init__(self):
        self._observer: Observer | None = None
        self._paths: list[str] = []
        self._handler: _LibraryHandler | None = None

    def start(self, paths: list[str], enqueue_fn, debounce_secs: int = 30):
        global watcher_instance
        self.stop()
        self._observer = Observer()
        self._handler = _LibraryHandler(enqueue_fn, debounce_secs)
        for p in paths:
            if Path(p).is_dir():
                self._observer.schedule(self._handler, str(p), recursive=True)
                self._paths.append(str(p))
                logger.info("[watcher] Monitoring: %s", p)
        if self._paths:
            self._observer.daemon = True
            self._observer.start()
            watcher_instance = self
            logger.info("[watcher] Started monitoring %d paths", len(self._paths))
        else:
            self._observer = None
            self._handler = None
            logger.warning("[watcher] No valid paths to monitor")

    def stop(self):
        if self._observer and self._observer.is_alive():
            self._observer.stop()
            self._observer.join(timeout=5)
        self._observer = None
        self._paths = []
        self._handler = None

    def pause(self):
        """Temporarily pause event handling (e.g., during full rescan)."""
        if self._handler:
            self._handler._paused = True
            logger.info("[watcher] Paused")

    def resume(self):
        """Resume event handling after a pause."""
        if self._handler:
            self._handler._paused = False
            logger.info("[watcher] Resumed")

    @property
    def is_paused(self) -> bool:
        return self._handler._paused if self._handler else False

    @property
    def is_running(self) -> bool:
        return self._observer is not None and self._observer.is_alive()

    @property
    def watched_paths(self) -> list[str]:
        return list(self._paths)


# Singleton instance for status checks from API
watcher_instance: LibraryWatcher | None = None
