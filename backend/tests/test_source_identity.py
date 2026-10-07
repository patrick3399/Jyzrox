"""Regression coverage for link-import source identity (HR-012)."""

import hashlib

import pytest


def test_source_identity_accepts_content_changes_without_directory_replacement(tmp_path):
    from services.source_identity import SourceDirectoryIdentity

    source = tmp_path / "source"
    source.mkdir()
    identity = SourceDirectoryIdentity.capture(source)
    (source / "new.jpg").write_bytes(b"new")

    identity.assert_unchanged("test")


def test_source_identity_rejects_rename_and_same_path_replacement(tmp_path):
    from services.source_identity import SourceDirectoryChangedError, SourceDirectoryIdentity

    source = tmp_path / "source"
    source.mkdir()
    identity = SourceDirectoryIdentity.capture(source)
    source.rename(tmp_path / "renamed")

    with pytest.raises(SourceDirectoryChangedError, match="unavailable"):
        identity.assert_unchanged("renamed")

    source.mkdir()
    with pytest.raises(SourceDirectoryChangedError, match="expected"):
        identity.assert_unchanged("replaced")


# ---------------------------------------------------------------------------
# Per-file identity (SourceDirectoryIdentity cannot see an in-place swap)
# ---------------------------------------------------------------------------


def test_hash_and_identity_describe_the_same_bytes(tmp_path):
    from services.source_identity import hash_file_with_identity

    target = tmp_path / "a.jpg"
    target.write_bytes(b"payload")

    digest, identity = hash_file_with_identity(target)

    assert digest == hashlib.sha256(b"payload").hexdigest()
    stat = target.stat()
    assert (identity.device, identity.inode) == (stat.st_dev, stat.st_ino)
    assert identity.size == stat.st_size
    identity.assert_unchanged("noop")  # must not raise


def test_replacing_a_file_in_place_is_detected_though_the_directory_is_untouched(tmp_path):
    """The exact gap the directory-level check misses.

    Same directory, same filename → the directory's inode never changes, so
    every SourceDirectoryIdentity assertion passes while link mode would record
    a sha256 that no longer matches the bytes at the stored path.
    """
    from services.source_identity import (
        SourceDirectoryIdentity,
        SourceFileChangedError,
        hash_file_with_identity,
    )

    target = tmp_path / "a.jpg"
    target.write_bytes(b"original")

    directory = SourceDirectoryIdentity.capture(tmp_path)
    _, identity = hash_file_with_identity(target)

    # Atomic replace: new inode behind the same name.
    replacement = tmp_path / "a.jpg.new"
    replacement.write_bytes(b"replaced content")
    replacement.replace(target)

    directory.assert_unchanged("after-swap")  # the old check is blind to this

    with pytest.raises(SourceFileChangedError, match="source file changed at commit"):
        identity.assert_unchanged("commit")


def test_rewriting_a_file_in_place_is_detected(tmp_path):
    """Same inode, new content — caught via size/mtime rather than inode."""
    import time

    from services.source_identity import SourceFileChangedError, hash_file_with_identity

    target = tmp_path / "a.jpg"
    target.write_bytes(b"original")
    _, identity = hash_file_with_identity(target)

    time.sleep(0.01)  # ensure mtime_ns actually moves
    with open(target, "r+b") as handle:
        handle.write(b"REWRITTEN-and-longer")

    with pytest.raises(SourceFileChangedError):
        identity.assert_unchanged("commit")


def test_deleted_file_is_reported_as_changed(tmp_path):
    from services.source_identity import SourceFileChangedError, hash_file_with_identity

    target = tmp_path / "a.jpg"
    target.write_bytes(b"payload")
    _, identity = hash_file_with_identity(target)
    target.unlink()

    with pytest.raises(SourceFileChangedError, match="unavailable"):
        identity.assert_unchanged("commit")


def test_hash_detects_a_file_growing_while_it_is_read(tmp_path, monkeypatch):
    """The read itself must not silently produce a digest for a moving target."""
    from services import source_identity as mod

    target = tmp_path / "a.jpg"
    target.write_bytes(b"x" * 200)

    real_fstat = mod.os.fstat
    calls = {"n": 0}

    def _fstat(fd):
        calls["n"] += 1
        stat = real_fstat(fd)
        if calls["n"] == 1:
            return stat
        # Second fstat (after the read) reports a different size/mtime.
        fields = list(stat)
        fields[6] = stat.st_size + 10  # st_size
        return type(stat)(tuple(fields))

    monkeypatch.setattr(mod.os, "fstat", _fstat)

    with pytest.raises(mod.SourceFileChangedError, match="while being hashed"):
        mod.hash_file_with_identity(target)
