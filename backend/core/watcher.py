"""Real-time library directory monitoring via watchdog."""

import logging
from pathlib import Path

from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver

from core.watcher_handler import _SUPPORTED_EXTS as _SUPPORTED_EXTS
from core.watcher_handler import _event_path as _event_path
from core.watcher_handler import _LibraryHandler as _LibraryHandler

logger = logging.getLogger(__name__)


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
