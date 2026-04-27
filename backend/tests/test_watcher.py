import time
from types import SimpleNamespace
from unittest.mock import MagicMock

from core.watcher import _LibraryHandler


def _event(path: str, is_directory: bool = False, dest_path: str | None = None):
    data = {"src_path": path, "is_directory": is_directory}
    if dest_path is not None:
        data["dest_path"] = dest_path
    return SimpleNamespace(**data)


def test_pause_buffers_dirty_paths_and_replays_on_resume():
    enqueue = MagicMock()
    handler = _LibraryHandler(enqueue, debounce_secs=0.01)

    handler.pause()
    handler.on_created(_event("/mnt/lib/gallery/001.jpg"))
    time.sleep(0.03)
    enqueue.assert_not_called()

    handler.resume()
    time.sleep(0.05)

    enqueue.assert_called_once_with("rescan_by_path_job", "/mnt/lib/gallery")


def test_shutdown_cancels_pending_debounce_timers():
    enqueue = MagicMock()
    handler = _LibraryHandler(enqueue, debounce_secs=10)

    handler.on_created(_event("/mnt/lib/gallery/001.jpg"))
    assert handler._pending

    handler.shutdown()

    assert handler._pending == {}
    enqueue.assert_not_called()


def test_deleted_non_media_file_does_not_schedule_rescan():
    enqueue = MagicMock()
    handler = _LibraryHandler(enqueue, debounce_secs=0.01)

    handler.on_deleted(_event("/mnt/lib/gallery/notes.txt"))
    time.sleep(0.03)

    enqueue.assert_not_called()
