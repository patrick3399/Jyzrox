"""Real-time library directory monitoring via watchdog."""

import logging
import os
import threading
import time
from os import fsdecode
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver

from services.media_formats import MEDIA_EXTENSIONS as _SUPPORTED_EXTS

logger = logging.getLogger(__name__)


def _event_path(path: str | bytes) -> Path:
    """Return a text path for watchdog events, which may use bytes paths."""
    return Path(fsdecode(path))


class _LibraryHandler(FileSystemEventHandler):
    """Debounced handler that enqueues SAQ jobs on file/dir changes."""

    def __init__(self, enqueue_fn, debounce_secs: int = 30):
        self._enqueue = enqueue_fn
        self._debounce_secs = debounce_secs
        self._pending: dict[str, threading.Timer] = {}
        self._dirty_while_paused: dict[str, tuple[str, tuple]] = {}
        self._recent_directory_creates: dict[str, tuple[float, int | None, int | None]] = {}
        self._recent_directory_deletes: dict[str, float] = {}
        self._recent_directory_moves: dict[tuple[str, str], float] = {}
        self._lock = threading.Lock()
        self._paused = False

    def _directory_event_window(self) -> float:
        return max(300.0, self._debounce_secs * 10.0)

    def _prune_directory_events(self, now: float) -> None:
        cutoff = now - self._directory_event_window()
        self._recent_directory_creates = {
            path: value for path, value in self._recent_directory_creates.items() if value[0] >= cutoff
        }
        self._recent_directory_deletes = {
            path: timestamp for path, timestamp in self._recent_directory_deletes.items() if timestamp >= cutoff
        }
        self._recent_directory_moves = {
            paths: timestamp for paths, timestamp in self._recent_directory_moves.items() if timestamp >= cutoff
        }

    @staticmethod
    def _is_within(path: str, directory: str) -> bool:
        return path == directory or path.startswith(directory.rstrip(os.sep) + os.sep)

    def _recent_directory_context(self, path: str, *, side: str) -> tuple[str, bool] | None:
        with self._lock:
            now = time.monotonic()
            self._prune_directory_events(now)
            cutoff = now - max(60.0, self._debounce_secs * 2.0)
            move_index = 1 if side == "created" else 0
            moved_roots = [
                paths[move_index]
                for paths, timestamp in self._recent_directory_moves.items()
                if timestamp >= cutoff and self._is_within(path, paths[move_index])
            ]
            if moved_roots:
                return max(moved_roots, key=len), True
            if side == "created":
                roots = [root for root, value in self._recent_directory_creates.items() if value[0] >= cutoff]
            else:
                roots = [root for root, timestamp in self._recent_directory_deletes.items() if timestamp >= cutoff]
            matching_roots = [root for root in roots if self._is_within(path, root)]
            if matching_roots:
                return max(matching_roots, key=len), False
            return None

    def _remember_directory_moved(self, old_path: str, new_path: str) -> None:
        with self._lock:
            now = time.monotonic()
            self._prune_directory_events(now)
            self._recent_directory_moves[(old_path, new_path)] = now

    def _cancel(self, key: str) -> None:
        with self._lock:
            timer = self._pending.pop(key, None)
            if timer:
                timer.cancel()
            self._dirty_while_paused.pop(key, None)

    def _remember_directory_created(self, path: str, device: int | None, inode: int | None) -> list[str]:
        with self._lock:
            now = time.monotonic()
            self._prune_directory_events(now)
            self._recent_directory_creates[path] = (now, device, inode)
            return list(self._recent_directory_deletes)

    def _remember_directory_deleted(self, path: str) -> list[tuple[str, int | None, int | None]]:
        with self._lock:
            now = time.monotonic()
            self._prune_directory_events(now)
            self._recent_directory_deletes[path] = now
            return [(path, value[1], value[2]) for path, value in self._recent_directory_creates.items()]

    def _schedule_directory_move_candidates(
        self,
        old_paths: list[str],
        new_path: str,
        destination_device: int | None,
        destination_inode: int | None,
    ) -> None:
        self._cancel(f"discover:{new_path}")
        self._cancel(f"rescan:{new_path}")
        for old_path in old_paths:
            self._remember_directory_moved(old_path, new_path)
            self._cancel(f"rescan:{old_path}")
        self._schedule(
            f"reconcile:{new_path}",
            "reconcile_library_path_job",
            sorted(set(old_paths)),
            new_path,
            destination_device,
            destination_inode,
        )

    def _schedule(self, key: str, job_name: str, *args):
        with self._lock:
            if self._paused:
                self._dirty_while_paused[key] = (job_name, args)
                return
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

    def pause(self):
        with self._lock:
            self._paused = True

    def resume(self):
        with self._lock:
            self._paused = False
            dirty = list(self._dirty_while_paused.items())
            self._dirty_while_paused.clear()
        for key, (job_name, args) in dirty:
            self._schedule(key, job_name, *args)

    def shutdown(self):
        with self._lock:
            for timer in self._pending.values():
                timer.cancel()
            self._pending.clear()
            self._dirty_while_paused.clear()
            self._recent_directory_creates.clear()
            self._recent_directory_deletes.clear()
            self._recent_directory_moves.clear()
            self._paused = False

    @property
    def is_paused(self) -> bool:
        return self._paused

    def on_created(self, event):
        if event.is_directory:
            destination = os.path.realpath(_event_path(event.src_path))
            try:
                stat_result = Path(destination).stat()
                destination_device = stat_result.st_dev
                destination_inode = stat_result.st_ino
            except OSError:
                destination_device = None
                destination_inode = None
            old_paths = self._remember_directory_created(destination, destination_device, destination_inode)
            if old_paths:
                self._schedule_directory_move_candidates(
                    old_paths,
                    destination,
                    destination_device,
                    destination_inode,
                )
            else:
                self._schedule(f"discover:{destination}", "auto_discover_job")
        else:
            event_path = os.path.realpath(_event_path(event.src_path))
            context = self._recent_directory_context(event_path, side="created")
            if context:
                root, is_paired_move = context
                if not is_paired_move:
                    self._schedule(f"discover:{root}", "auto_discover_job")
                return
            ext = Path(event_path).suffix.lower()
            if ext in _SUPPORTED_EXTS:
                parent = str(Path(event_path).parent)
                self._schedule(f"rescan:{parent}", "rescan_by_path_job", parent)

    def on_deleted(self, event):
        if event.is_directory:
            old_path = os.path.realpath(_event_path(event.src_path))
            destinations = self._remember_directory_deleted(old_path)
            for new_path, destination_device, destination_inode in destinations:
                with self._lock:
                    old_paths = list(self._recent_directory_deletes)
                self._schedule_directory_move_candidates(
                    old_paths,
                    new_path,
                    destination_device,
                    destination_inode,
                )
        else:
            event_path = os.path.realpath(_event_path(event.src_path))
            if self._recent_directory_context(event_path, side="deleted"):
                return
            ext = Path(event_path).suffix.lower()
            if ext in _SUPPORTED_EXTS:
                parent = str(Path(event_path).parent)
                self._schedule(f"rescan:{parent}", "rescan_by_path_job", parent)

    def on_moved(self, event):
        if event.is_directory:
            destination = _event_path(event.dest_path)
            try:
                stat_result = destination.stat()
                destination_device = stat_result.st_dev
                destination_inode = stat_result.st_ino
            except OSError:
                destination_device = None
                destination_inode = None
            old_path = os.path.realpath(_event_path(event.src_path))
            new_path = os.path.realpath(destination)
            self._remember_directory_moved(old_path, new_path)
            self._cancel(f"rescan:{old_path}")
            self._cancel(f"rescan:{new_path}")
            self._schedule(
                f"move:{old_path}",
                "move_library_path_job",
                old_path,
                new_path,
                destination_device,
                destination_inode,
            )
        else:
            old_path = os.path.realpath(_event_path(event.src_path))
            new_path = os.path.realpath(_event_path(event.dest_path))
            old_context = self._recent_directory_context(old_path, side="deleted")
            new_context = self._recent_directory_context(new_path, side="created")
            if old_context or new_context:
                if new_context and not new_context[1]:
                    self._schedule(f"discover:{new_context[0]}", "auto_discover_job")
                return
            old_ext = Path(old_path).suffix.lower()
            new_ext = Path(new_path).suffix.lower()
            old_parent = str(Path(old_path).parent)
            new_parent = str(Path(new_path).parent)
            if old_ext in _SUPPORTED_EXTS:
                self._schedule(f"rescan:{old_parent}", "rescan_by_path_job", old_parent)
            if new_parent != old_parent and new_ext in _SUPPORTED_EXTS:
                self._schedule(f"rescan:{new_parent}", "rescan_by_path_job", new_parent)

    def on_modified(self, event):
        # Only care about file modifications (e.g., image replaced in-place)
        if not event.is_directory:
            event_path = os.path.realpath(_event_path(event.src_path))
            context = self._recent_directory_context(event_path, side="created")
            if context:
                root, is_paired_move = context
                if not is_paired_move:
                    self._schedule(f"discover:{root}", "auto_discover_job")
                return
            ext = Path(event_path).suffix.lower()
            if ext in _SUPPORTED_EXTS:
                parent = str(Path(event_path).parent)
                self._schedule(f"rescan:{parent}", "rescan_by_path_job", parent)


class LibraryWatcher:
    """Manages watchdog Observer for library directories."""

    def __init__(self):
        self._observer: BaseObserver | None = None
        self._paths: list[str] = []
        self._handler: _LibraryHandler | None = None

    def start(self, paths: list[str], enqueue_fn, debounce_secs: int = 30):
        global watcher_instance
        self.stop()

        from core.config import settings

        use_polling = settings.watcher_use_polling

        if not use_polling:
            try:
                self._observer = Observer()
                self._handler = _LibraryHandler(enqueue_fn, debounce_secs)
                for p in paths:
                    if Path(p).is_dir():
                        self._observer.schedule(self._handler, str(p), recursive=True)
                        self._paths.append(str(p))
                        logger.info("[watcher] Monitoring: %s", p)
            except OSError:
                logger.warning(
                    "[watcher] inotify limit hit, falling back to polling (interval=%ds)",
                    settings.watcher_polling_interval,
                )
                if self._observer is not None and self._observer.is_alive():
                    self._observer.stop()
                use_polling = True
                self._paths = []

        if use_polling:
            from watchdog.observers.polling import PollingObserver

            self._observer = PollingObserver(timeout=settings.watcher_polling_interval)
            self._handler = _LibraryHandler(enqueue_fn, debounce_secs)
            for p in paths:
                if Path(p).is_dir():
                    self._observer.schedule(self._handler, str(p), recursive=True)
                    self._paths.append(str(p))
                    logger.info("[watcher] Monitoring (polling): %s", p)

        if self._paths:
            observer = self._observer
            if observer is None:
                raise RuntimeError("Watcher has paths but no observer")
            observer.daemon = True
            observer.start()
            watcher_instance = self
            logger.info(
                "[watcher] Started monitoring %d paths (polling=%s)",
                len(self._paths),
                use_polling,
            )
        else:
            self._observer = None
            self._handler = None
            logger.warning("[watcher] No valid paths to monitor")

    def stop(self):
        if self._handler:
            self._handler.shutdown()
        if self._observer and self._observer.is_alive():
            self._observer.stop()
            self._observer.join(timeout=5)
        self._observer = None
        self._paths = []
        self._handler = None

    def pause(self):
        """Temporarily pause event handling (e.g., during full rescan)."""
        if self._handler:
            self._handler.pause()
            logger.info("[watcher] Paused")

    def resume(self):
        """Resume event handling after a pause."""
        if self._handler:
            self._handler.resume()
            logger.info("[watcher] Resumed")

    @property
    def is_paused(self) -> bool:
        return self._handler.is_paused if self._handler else False

    @property
    def is_running(self) -> bool:
        return self._observer is not None and self._observer.is_alive()

    @property
    def is_polling(self) -> bool:
        from watchdog.observers.polling import PollingObserver

        return isinstance(self._observer, PollingObserver)

    @property
    def watched_paths(self) -> list[str]:
        return list(self._paths)


# Singleton instance for status checks from API
watcher_instance: LibraryWatcher | None = None
