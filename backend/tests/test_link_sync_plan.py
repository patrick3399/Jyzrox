"""Pure diff logic for link-mode gallery sync (ADR 0014)."""

from services.link_sync import SETTLE_NS, FileStat, KnownImage, plan_link_sync, scan_media_files

NOW = 10_000_000_000_000
OLD = NOW - 60_000_000_000


def _file(name: str, size: int = 10, mtime_ns: int = OLD) -> FileStat:
    return FileStat(path=f"/lib/g/{name}", name=name, size=size, mtime_ns=mtime_ns)


def _known(image_id: int, name: str, size: int | None = 10, mtime_ns: int | None = OLD) -> KnownImage:
    return KnownImage(
        image_id=image_id, external_path=f"/lib/g/{name}", sha256=f"sha-{image_id}", size=size, mtime_ns=mtime_ns
    )


def test_identical_fingerprint_is_unchanged_and_needs_no_hash():
    plan = plan_link_sync([_known(1, "001.jpg")], [_file("001.jpg")], now_ns=NOW)

    assert [image.image_id for image in plan.unchanged] == [1]
    assert plan.needs_hash == []
    assert plan.missing == []


def test_new_filename_is_new_and_ordered_naturally():
    plan = plan_link_sync([], [_file("10.jpg"), _file("2.jpg")], now_ns=NOW)

    assert [file.name for file in plan.new] == ["2.jpg", "10.jpg"]


def test_same_name_with_different_size_or_mtime_is_changed():
    plan = plan_link_sync(
        [_known(1, "a.jpg"), _known(2, "b.jpg")],
        [_file("a.jpg", size=11), _file("b.jpg", mtime_ns=OLD + 1)],
        now_ns=NOW,
    )

    assert [(image.image_id, file.name) for image, file in plan.changed] == [(1, "a.jpg"), (2, "b.jpg")]
    assert [file.name for file in plan.needs_hash] == ["a.jpg", "b.jpg"]


def test_row_without_fingerprint_is_adopted_not_rehashed():
    plan = plan_link_sync([_known(1, "a.jpg", size=None, mtime_ns=None)], [_file("a.jpg")], now_ns=NOW)

    assert [(image.image_id, file.name) for image, file in plan.adopt] == [(1, "a.jpg")]
    assert plan.needs_hash == []


def test_row_whose_file_is_gone_is_missing():
    plan = plan_link_sync([_known(1, "gone.jpg")], [], now_ns=NOW)

    assert [image.image_id for image in plan.missing] == [1]


def test_file_modified_within_settle_window_is_deferred():
    fresh = NOW - SETTLE_NS + 1
    plan = plan_link_sync(
        [_known(1, "rewriting.jpg")],
        [_file("copying.jpg", mtime_ns=fresh), _file("rewriting.jpg", size=99, mtime_ns=fresh)],
        now_ns=NOW,
    )

    assert sorted(file.name for file in plan.unsettled) == ["copying.jpg", "rewriting.jpg"]
    assert plan.new == []
    assert plan.changed == []
    assert plan.missing == []


def test_scan_media_files_lists_only_media_with_stat(tmp_path):
    (tmp_path / "001.jpg").write_bytes(b"abc")
    (tmp_path / "notes.txt").write_bytes(b"x")
    (tmp_path / "sub.jpg").mkdir()

    files = scan_media_files(tmp_path)

    assert [(file.name, file.size, file.path) for file in files] == [("001.jpg", 3, str(tmp_path / "001.jpg"))]
    assert files[0].mtime_ns == (tmp_path / "001.jpg").stat().st_mtime_ns


def test_library_root_missing_or_empty_is_unavailable(tmp_path):
    from services.link_sync import library_root_available

    empty = tmp_path / "empty"
    empty.mkdir()
    populated = tmp_path / "populated"
    (populated / "g").mkdir(parents=True)

    assert library_root_available(str(tmp_path / "absent")) is False
    assert library_root_available(str(empty)) is False
    assert library_root_available(str(populated)) is True
    assert library_root_available(None) is True
