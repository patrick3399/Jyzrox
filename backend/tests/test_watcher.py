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


def test_directory_move_preserves_old_new_pair_and_destination_identity(tmp_path):
    enqueue = MagicMock()
    handler = _LibraryHandler(enqueue, debounce_secs=0.01)
    old_path = tmp_path / "old"
    new_path = tmp_path / "new"
    old_path.mkdir()
    old_path.rename(new_path)
    destination_stat = new_path.stat()

    handler.on_moved(_event(str(old_path), is_directory=True, dest_path=str(new_path)))
    handler.on_moved(
        _event(
            str(old_path / "001.jpg"),
            dest_path=str(new_path / "001.jpg"),
        )
    )
    time.sleep(0.05)

    enqueue.assert_called_once_with(
        "move_library_path_job",
        str(old_path),
        str(new_path),
        destination_stat.st_dev,
        destination_stat.st_ino,
    )


def test_unpaired_cross_root_events_are_reconciled_before_discovery(tmp_path):
    enqueue = MagicMock()
    handler = _LibraryHandler(enqueue, debounce_secs=0.01)
    old_path = tmp_path / "root-a" / "old"
    new_path = tmp_path / "root-b" / "new"
    old_path.parent.mkdir()
    new_path.mkdir(parents=True)
    new_image = new_path / "001.jpg"
    new_image.write_bytes(b"image")
    destination_stat = new_path.stat()

    handler.on_created(_event(str(new_path), is_directory=True))
    handler.on_created(_event(str(new_image)))
    handler.on_deleted(_event(str(old_path), is_directory=True))
    handler.on_deleted(_event(str(old_path / "001.jpg")))
    time.sleep(0.05)

    enqueue.assert_called_once_with(
        "reconcile_library_path_job",
        [str(old_path)],
        str(new_path),
        destination_stat.st_dev,
        destination_stat.st_ino,
    )
