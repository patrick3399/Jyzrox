"""Unit tests for core/local_category_plan.py.

Pure functions only — no DB, no filesystem, no settings.
"""

import pytest

from core.local_category_plan import (
    MigrationError,
    assert_safe_source_id_unique,
    load_mapping,
    normalize_category,
    safe_source_id,
    transform_path,
    transform_source_id,
    validate_mapping,
)

# ---------------------------------------------------------------------------
# safe_source_id — must stay byte-identical to services.cas.safe_source_id
# ---------------------------------------------------------------------------


def test_safe_source_id_matches_cas_implementation_for_representative_ids():
    """The stdlib copy must not drift from the production implementation."""
    from services.cas import safe_source_id as cas_impl

    samples = [
        "abfluss/2025/12-02-[DNF]x",
        "Cosplay/abfluss/2025/12-02-[DNF]x",
        "  padded/id  ",
        "a/../b",
        "plain",
        "Image Set/omochi/omochi/vol1",
    ]
    for sid in samples:
        assert safe_source_id(sid) == cas_impl(sid), sid


# ---------------------------------------------------------------------------
# load_mapping / validate_mapping
# ---------------------------------------------------------------------------


def test_load_mapping_reads_first_two_columns_and_skips_comments(tmp_path):
    f = tmp_path / "map.tsv"
    f.write_text(
        "# comment line\nabfluss\tArtist CG\t555\tdate-bucket\tsample\nomochi\tCosplay\n\n",
        encoding="utf-8",
    )
    assert load_mapping(str(f)) == {"abfluss": "Artist CG", "omochi": "Cosplay"}


def test_load_mapping_rejects_duplicate_artist_rows(tmp_path):
    f = tmp_path / "map.tsv"
    f.write_text("abfluss\tCosplay\nabfluss\tManga\n", encoding="utf-8")
    with pytest.raises(MigrationError, match="duplicate artist"):
        load_mapping(str(f))


def test_load_mapping_rejects_row_without_category(tmp_path):
    f = tmp_path / "map.tsv"
    f.write_text("abfluss\t\t555\n", encoding="utf-8")
    with pytest.raises(MigrationError, match="empty category"):
        load_mapping(str(f))


@pytest.mark.parametrize("bad", ["a/b", "a\\b", "a__b", "a..b", "", " ", "x" * 65])
def test_validate_mapping_rejects_unsafe_category_name(bad):
    """Separators, the safe_source_id escape sequence and '..' must be refused."""
    with pytest.raises(MigrationError):
        validate_mapping({"abfluss": bad}, {"abfluss"})


def test_validate_mapping_rejects_artist_missing_from_mapping():
    with pytest.raises(MigrationError, match="not covered"):
        validate_mapping({"abfluss": "Cosplay"}, {"abfluss", "omochi"})


def test_validate_mapping_rejects_mapping_entry_with_no_galleries():
    with pytest.raises(MigrationError, match="unknown artist"):
        validate_mapping({"abfluss": "Cosplay", "ghost": "Manga"}, {"abfluss"})


def test_validate_mapping_accepts_exact_cover():
    validate_mapping({"abfluss": "Cosplay", "omochi": "Image Set"}, {"abfluss", "omochi"})


# ---------------------------------------------------------------------------
# transform_source_id / transform_path
# ---------------------------------------------------------------------------


def test_transform_source_id_inserts_category_before_artist():
    m = {"abfluss": "Artist CG"}
    assert transform_source_id("abfluss/2025/12-02-x", m) == "Artist CG/abfluss/2025/12-02-x"


def test_transform_source_id_rejects_already_migrated_id():
    """Re-running against a migrated id must fail loudly, not double-prefix."""
    m = {"abfluss": "Artist CG"}
    with pytest.raises(MigrationError, match="unknown artist"):
        transform_source_id("Artist CG/abfluss/2025/12-02-x", m)


def test_transform_source_id_rejects_wrong_segment_count():
    m = {"abfluss": "Artist CG"}
    with pytest.raises(MigrationError, match="expected 3 segments"):
        transform_source_id("abfluss/2025", m)


def test_transform_path_rewrites_only_the_segment_after_root():
    m = {"abfluss": "Artist CG"}
    got = transform_path("/mnt/img/abfluss/2025/x/001.png", "/mnt/img", m)
    assert got == "/mnt/img/Artist CG/abfluss/2025/x/001.png"


def test_transform_path_rejects_path_outside_root():
    m = {"abfluss": "Artist CG"}
    with pytest.raises(MigrationError, match="outside library root"):
        transform_path("/other/abfluss/2025/x/001.png", "/mnt/img", m)


def test_transform_path_does_not_match_artist_name_as_bare_prefix():
    """'abfluss2' must not be rewritten by an 'abfluss' mapping entry."""
    m = {"abfluss": "Artist CG"}
    with pytest.raises(MigrationError, match="unknown artist"):
        transform_path("/mnt/img/abfluss2/2025/x/001.png", "/mnt/img", m)


# ---------------------------------------------------------------------------
# assert_safe_source_id_unique
# ---------------------------------------------------------------------------


def test_assert_safe_source_id_unique_passes_for_distinct_ids():
    assert_safe_source_id_unique(["Cosplay/a/b/c", "Manga/a/b/c"])


def test_assert_safe_source_id_unique_rejects_post_transform_collision():
    """'a/b__c' and 'a/b/c' both sanitize to 'a__b__c' (safe_source_id is not injective)."""
    with pytest.raises(MigrationError, match="collision"):
        assert_safe_source_id_unique(["a/b__c", "a/b/c"])


# ---------------------------------------------------------------------------
# normalize_category — lenient runtime normalization
#
# This is deliberately NOT the same policy as `_validate_category_name`
# (the strict migration-time validator, which raises MigrationError instead
# of returning None). Migration is *creating* directory names and owns the
# whole namespace, so it can afford to be strict. Runtime is *reading*
# whatever is already on disk and must stay lenient but safe: folder names
# it cannot safely use become `None` rather than aborting discovery/import.
# ---------------------------------------------------------------------------


def test_normalize_category_returns_plain_string_unchanged():
    assert normalize_category("Cosplay") == "Cosplay"


def test_normalize_category_strips_surrounding_whitespace():
    assert normalize_category("  Cosplay  ") == "Cosplay"


@pytest.mark.parametrize("value", ["", "   "])
def test_normalize_category_returns_none_for_empty_or_whitespace_only_string(value):
    assert normalize_category(value) is None


def test_normalize_category_returns_none_for_none_input():
    assert normalize_category(None) is None


@pytest.mark.parametrize("value", [123, True, {"a": 1}, ["x"]])
def test_normalize_category_returns_none_for_non_string_input_without_raising(value):
    """A path-derived regex group is always a str, but normalize_category is
    also reachable from less trusted call sites (e.g. a JSON body field that
    only Pydantic-typed loosely). Non-str input must degrade to None, never
    raise — a badly typed category must not be able to abort discovery or
    import."""
    assert normalize_category(value) is None


def test_normalize_category_returns_none_for_string_longer_than_64_chars():
    assert normalize_category("x" * 65) is None


def test_normalize_category_returns_value_for_string_exactly_64_chars():
    """The length boundary must not off-by-one and reject a legitimate
    64-char category."""
    value = "x" * 64
    assert normalize_category(value) == value


@pytest.mark.parametrize("value", ["a/b", "a\\b"])
def test_normalize_category_returns_none_for_path_separator_characters(value):
    assert normalize_category(value) is None


def test_normalize_category_preserves_double_underscore_segment():
    """'__' is a hazard only at migration time, where it gets fed into
    safe_source_id to build a directory name and would collide with the
    escape sequence produced for a literal '/' (see _validate_category_name).
    At runtime, ensure_library_dir's ownership marker already guards against
    that class of collision, so rejecting '__' here would be inconsistent
    with the rest of the runtime path and would silently discard a
    legitimate, pre-existing folder name."""
    assert normalize_category("a__b") == "a__b"


def test_normalize_category_preserves_leading_dot_dot_segment():
    """Same reasoning as test_normalize_category_preserves_double_underscore_segment:
    '..' is only unsafe when migration uses it to construct a directory name;
    it is not a distinct hazard for a value read back from an existing
    directory at runtime."""
    assert normalize_category("..x") == "..x"
