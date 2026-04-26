"""
Unit tests for core/local_patterns.py.

No DB or HTTP fixtures needed — these are pure function tests.
Covers previously uncovered lines: 39-43, 61, 63, 65, 71, 74, 79, 90, 99-104.
"""

from pathlib import Path

import pytest

from core.local_patterns import (
    PatternError,
    build_library_pattern_regex,
    pattern_match,
    split_library_pattern_path,
    validate_library_pattern,
)


# ---------------------------------------------------------------------------
# split_library_pattern_path — placeholder branch (lines 39-43)
# ---------------------------------------------------------------------------


def test_split_library_pattern_path_with_placeholder_parses_root_and_pattern():
    """Path containing '{' must split into static root and placeholder pattern."""
    result = split_library_pattern_path("/srv/library/{title}")
    assert result.pattern == "{title}"
    # root_path should be the realpath of /srv/library
    assert result.root_path.endswith("library") or result.root_path == str(
        Path("/srv/library").resolve()
    )


def test_split_library_pattern_path_with_nested_placeholder():
    """Path like /data/{artist}/{title} extracts /data as root."""
    result = split_library_pattern_path("/data/{artist}/{title}")
    assert result.pattern == "{artist}/{title}"
    assert result.root_path == str(Path("/data").resolve())


def test_split_library_pattern_path_leading_placeholder_uses_root():
    """When path starts with '{', root should fall back to os.sep realpath."""
    result = split_library_pattern_path("{title}")
    assert result.pattern == "{title}"
    # root_path is realpath of '' -> os.sep -> filesystem root
    assert result.root_path  # non-empty


# ---------------------------------------------------------------------------
# validate_library_pattern — individual error branches
# ---------------------------------------------------------------------------


def test_validate_library_pattern_empty_raises_pattern_error():
    """Empty pattern (after normalisation) must raise PatternError (line 61)."""
    with pytest.raises(PatternError, match="empty"):
        validate_library_pattern("")


def test_validate_library_pattern_too_long_raises_pattern_error():
    """Pattern longer than 500 chars must raise PatternError (line 63)."""
    long_pattern = "x" * 493 + "/{title}"
    assert len(long_pattern) > 500
    with pytest.raises(PatternError, match="too long"):
        validate_library_pattern(long_pattern)


def test_validate_library_pattern_missing_title_raises_pattern_error():
    """Pattern without {title} must raise PatternError (line 65)."""
    with pytest.raises(PatternError, match="must include"):
        validate_library_pattern("{author}")


def test_validate_library_pattern_invalid_placeholder_name_raises_pattern_error():
    """Placeholder name starting with digit must raise PatternError (line 71)."""
    with pytest.raises(PatternError, match="Invalid placeholder name"):
        validate_library_pattern("{1invalid}/{title}")


def test_validate_library_pattern_duplicate_placeholder_raises_pattern_error():
    """Repeated placeholder name must raise PatternError (line 74)."""
    with pytest.raises(PatternError, match="Duplicate placeholder"):
        validate_library_pattern("{dup}/{dup}/{title}")


def test_validate_library_pattern_unbalanced_brace_raises_pattern_error():
    """Trailing '}' after placeholder split must raise PatternError (line 79)."""
    with pytest.raises(PatternError, match="Invalid placeholder syntax"):
        validate_library_pattern("{title}}")


# ---------------------------------------------------------------------------
# build_library_pattern_regex — wildcard placeholder (line 90)
# ---------------------------------------------------------------------------


def test_build_library_pattern_regex_underscore_uses_non_capturing_group():
    """'_' placeholder must produce a non-capturing group (?:[^/]+) (line 90)."""
    pattern = "{_}/{title}"
    regex = build_library_pattern_regex(pattern)
    pattern_str = regex.pattern
    assert "(?:[^/]+)" in pattern_str
    # Ensure no named group for '_'
    assert "?P<_>" not in pattern_str


def test_build_library_pattern_regex_named_placeholder_creates_named_group():
    """Normal placeholder must produce a named capture group."""
    regex = build_library_pattern_regex("{artist}/{title}")
    assert "?P<artist>" in regex.pattern
    assert "?P<title>" in regex.pattern


# ---------------------------------------------------------------------------
# pattern_match — ValueError (lines 99-104) and no-match branch
# ---------------------------------------------------------------------------


def test_pattern_match_candidate_outside_root_returns_none():
    """candidate.relative_to(root) raising ValueError must return None (lines 99-102)."""
    result = pattern_match("{title}", Path("/root"), Path("/other/path"))
    assert result is None


def test_pattern_match_candidate_depth_mismatch_returns_none():
    """Pattern with single segment should not match a two-segment relative path."""
    result = pattern_match("{title}", Path("/root"), Path("/root/no-match/extra"))
    assert result is None


def test_pattern_match_success_returns_groupdict():
    """Matching candidate must return the named captures as a dict."""
    result = pattern_match("{title}", Path("/root"), Path("/root/my-gallery"))
    assert result == {"title": "my-gallery"}


def test_pattern_match_multi_segment_success():
    """Multi-segment pattern with multiple placeholders must match correctly."""
    result = pattern_match(
        "{artist}/{title}", Path("/lib"), Path("/lib/john/painting")
    )
    assert result == {"artist": "john", "title": "painting"}
