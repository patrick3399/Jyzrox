"""
Tests for gallery-dl metadata parsing utilities.

Covers:
- _extract_title: dot-notation field access, fallback chain, truncation
- parse_gallery_dl_import: source detection, tag extraction, fallback_source
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# _extract_title
# ---------------------------------------------------------------------------


class TestExtractTitleSimpleField:
    """_extract_title resolves a standard top-level title field."""

    def test_extract_title_simple_field_returns_value(self):
        """A top-level 'title' field is returned verbatim (up to 200 chars)."""
        from plugins.builtin.gallery_dl._metadata import _extract_title

        meta = {"title": "My Gallery Title"}
        result = _extract_title("gallery_dl", meta, "123")
        assert result == "My Gallery Title"

    def test_extract_title_simple_field_strips_nothing(self):
        """Returned title is the exact string stored in meta, not stripped."""
        from plugins.builtin.gallery_dl._metadata import _extract_title

        meta = {"title": "  spaced title  "}
        result = _extract_title("gallery_dl", meta, "abc")
        assert result == "  spaced title  "


class TestExtractTitleDotNotation:
    """_extract_title resolves dot-notation paths into nested dicts."""

    def test_extract_title_dot_notation_resolves_nested_value(self):
        """'author.name' correctly accesses meta['author']['name']."""
        from plugins.builtin.gallery_dl._metadata import _extract_title

        meta = {"author": {"name": "artist_handle"}}
        result = _extract_title("twitter", meta, "tweet_1")
        assert result == "artist_handle"

    def test_extract_title_dot_notation_missing_intermediate_falls_through(self):
        """'author.name' when meta has no 'author' key falls through to next field."""
        from plugins.builtin.gallery_dl._metadata import _extract_title

        # Twitter has title_fields=("author.name", "user.name", "username")
        # No "author", no "user.name", but has "username"
        meta = {"username": "fallback_user"}
        result = _extract_title("twitter", meta, "tweet_2")
        assert result == "fallback_user"

    def test_extract_title_dot_notation_non_dict_intermediate_falls_through(self):
        """'author.name' when meta['author'] is a string (not dict) falls through."""
        from plugins.builtin.gallery_dl._metadata import _extract_title

        # "author" is a plain string — cannot access .get("name") on it
        meta = {"author": "just_a_string", "username": "correct_user"}
        result = _extract_title("twitter", meta, "tweet_3")
        assert result == "correct_user"


class TestExtractTitleTwitterMetadata:
    """_extract_title handles real Twitter metadata structures."""

    def test_extract_title_twitter_metadata_returns_author_name(self):
        """Full Twitter metadata with author.name returns the author handle."""
        from plugins.builtin.gallery_dl._metadata import _extract_title

        meta = {
            "tweet_id": "1234567890",
            "author": {"name": "cool_artist", "id": 42},
            "content": "Check out my new art piece!",
        }
        result = _extract_title("twitter", meta, "1234567890")
        assert result == "cool_artist"

    def test_extract_title_twitter_metadata_prefers_author_over_username(self):
        """author.name takes priority over the top-level 'username' field."""
        from plugins.builtin.gallery_dl._metadata import _extract_title

        meta = {
            "author": {"name": "preferred_handle"},
            "username": "other_handle",
        }
        result = _extract_title("twitter", meta, "999")
        assert result == "preferred_handle"

    def test_extract_title_twitter_no_author_falls_back_to_username(self):
        """Twitter metadata without author dict falls through to 'username'."""
        from plugins.builtin.gallery_dl._metadata import _extract_title

        # title_fields=("author.name", "user.name", "username") — first two absent
        meta = {"username": "fallback_handle", "content": "some tweet text"}
        result = _extract_title("twitter", meta, "777")
        assert result == "fallback_handle"

    def test_extract_title_twitter_no_author_user_name_fallback(self):
        """Twitter metadata with user dict resolves 'user.name' as second priority."""
        from plugins.builtin.gallery_dl._metadata import _extract_title

        meta = {
            # no "author" key
            "user": {"name": "user_dot_name_handle"},
            "username": "username_field",
        }
        result = _extract_title("twitter", meta, "555")
        assert result == "user_dot_name_handle"


class TestExtractTitleFallbackToContent:
    """_extract_title falls back to description/content when no title_fields match."""

    def test_extract_title_fallback_to_description(self):
        """When no title_fields match, 'description' is used as fallback."""
        from plugins.builtin.gallery_dl._metadata import _extract_title

        # gallery_dl (unknown source) has default title_fields=("title", "title_en")
        # Neither is present, so fallback chain kicks in
        meta = {"description": "A description of the gallery"}
        result = _extract_title("gallery_dl", meta, "no_title")
        assert result == "A description of the gallery"

    def test_extract_title_fallback_to_content(self):
        """When description is also absent, 'content' is used."""
        from plugins.builtin.gallery_dl._metadata import _extract_title

        meta = {"content": "Content field text"}
        result = _extract_title("gallery_dl", meta, "no_title")
        assert result == "Content field text"

    def test_extract_title_fallback_to_source_id_when_all_absent(self):
        """When all fallbacks are absent, returns '{source}_{source_id}'."""
        from plugins.builtin.gallery_dl._metadata import _extract_title

        meta = {}
        result = _extract_title("gallery_dl", meta, "abc123")
        assert result == "gallery_dl_abc123"


class TestExtractTitleTruncation:
    """_extract_title truncates titles longer than 200 characters."""

    def test_extract_title_truncates_at_200_chars(self):
        """A title longer than 200 chars is sliced to exactly 200 chars."""
        from plugins.builtin.gallery_dl._metadata import _extract_title

        long_title = "A" * 250
        meta = {"title": long_title}
        result = _extract_title("gallery_dl", meta, "xyz")
        assert len(result) == 200
        assert result == "A" * 200

    def test_extract_title_exactly_200_chars_not_truncated(self):
        """A title of exactly 200 chars passes through unchanged."""
        from plugins.builtin.gallery_dl._metadata import _extract_title

        exact_title = "B" * 200
        meta = {"title": exact_title}
        result = _extract_title("gallery_dl", meta, "xyz")
        assert result == exact_title
        assert len(result) == 200

    def test_extract_title_description_fallback_truncated_at_120_chars(self):
        """description fallback is truncated at 120 chars, not 200."""
        from plugins.builtin.gallery_dl._metadata import _extract_title

        long_desc = "D" * 200
        meta = {"description": long_desc}
        result = _extract_title("gallery_dl", meta, "xyz")
        assert len(result) == 120
        assert result == "D" * 120


# ---------------------------------------------------------------------------
# parse_gallery_dl_import
# ---------------------------------------------------------------------------


class TestParseTwitterImport:
    """parse_gallery_dl_import correctly parses Twitter/X metadata."""

    def test_parse_twitter_import_source_and_source_id(self, tmp_path: Path):
        """Full Twitter metadata yields source='twitter' and source_id from tweet_id."""
        from plugins.builtin.gallery_dl._metadata import parse_gallery_dl_import

        meta = {
            "category": "twitter",
            "tweet_id": 9876543210,
            "author": {"name": "my_artist"},
            "content": "great art post",
        }
        result = parse_gallery_dl_import(tmp_path, meta)
        assert result.source == "twitter"
        assert result.source_id == "9876543210"

    def test_parse_twitter_import_title_from_author_name(self, tmp_path: Path):
        """Title is extracted from author.name for Twitter source."""
        from plugins.builtin.gallery_dl._metadata import parse_gallery_dl_import

        meta = {
            "category": "twitter",
            "tweet_id": 1111111111,
            "author": {"name": "artsy_person"},
        }
        result = parse_gallery_dl_import(tmp_path, meta)
        assert result.title == "artsy_person"

    def test_parse_twitter_import_x_category_unknown_falls_back_to_gallery_dl(self, tmp_path: Path):
        """'x' is not a registered alias, so source falls back to 'gallery_dl'."""
        from plugins.builtin.gallery_dl._metadata import parse_gallery_dl_import

        meta = {
            "category": "x",
            "tweet_id": 2222222222,
            "author": {"name": "x_user"},
        }
        result = parse_gallery_dl_import(tmp_path, meta)
        # 'x' has no entry in _ALIASES or _BY_SOURCE -> _DEFAULT_CONFIG -> source_id="gallery_dl"
        assert result.source == "gallery_dl"

    def test_parse_twitter_import_missing_tweet_id_uses_dir_name(self, tmp_path: Path):
        """When tweet_id is absent, source_id falls back to dest_dir.name."""
        from plugins.builtin.gallery_dl._metadata import parse_gallery_dl_import

        named_dir = tmp_path / "my_gallery_folder"
        named_dir.mkdir()

        meta = {"category": "twitter", "author": {"name": "handle"}}
        result = parse_gallery_dl_import(named_dir, meta)
        assert result.source_id == "my_gallery_folder"


class TestParseImportWithTags:
    """parse_gallery_dl_import correctly extracts and formats tags."""

    def test_parse_import_tags_dict_produces_namespace_name_format(self, tmp_path: Path):
        """Tags stored as dict {namespace: [name, ...]} are emitted as 'namespace:name'."""
        from plugins.builtin.gallery_dl._metadata import parse_gallery_dl_import

        meta = {
            "category": "danbooru",
            "id": 55555,
            "tags": {
                "artist": ["author_name"],
                "character": ["char_a", "char_b"],
                "general": ["tag1"],
            },
        }
        result = parse_gallery_dl_import(tmp_path, meta)
        # Danbooru has normalize_namespaces=True, so "artist" stays "artist"
        assert "artist:author_name" in result.tags
        assert "character:char_a" in result.tags
        assert "character:char_b" in result.tags
        assert "general:tag1" in result.tags

    def test_parse_import_tags_list_passes_through(self, tmp_path: Path):
        """Tags stored as a flat list are passed through unchanged."""
        from plugins.builtin.gallery_dl._metadata import parse_gallery_dl_import

        meta = {
            "category": "gallery_dl",
            "tags": ["artist:someone", "character:hero", "general:action"],
        }
        result = parse_gallery_dl_import(tmp_path, meta)
        assert "artist:someone" in result.tags
        assert "character:hero" in result.tags

    def test_parse_import_tags_normalize_copyright_namespace(self, tmp_path: Path):
        """For sources with normalize_namespaces=True, 'copyright' is mapped to 'parody'."""
        from plugins.builtin.gallery_dl._metadata import parse_gallery_dl_import

        meta = {
            "category": "danbooru",
            "id": 77777,
            "tags": {"copyright": ["some_series"]},
        }
        result = parse_gallery_dl_import(tmp_path, meta)
        # NAMESPACE_MAP maps "copyright" -> "parody"
        assert "parody:some_series" in result.tags
        assert "copyright:some_series" not in result.tags

    def test_parse_import_rating_tag_added(self, tmp_path: Path):
        """A 'rating' field in metadata produces a 'rating:<value>' tag."""
        from plugins.builtin.gallery_dl._metadata import parse_gallery_dl_import

        meta = {
            "category": "danbooru",
            "id": 88888,
            "tags": {"general": ["safe_content"]},
            "rating": "s",
        }
        result = parse_gallery_dl_import(tmp_path, meta)
        assert "rating:s" in result.tags


class TestParseImportFallbackSource:
    """parse_gallery_dl_import uses fallback_source when metadata has no 'category'."""

    def test_parse_import_fallback_source_used_when_no_category(self, tmp_path: Path):
        """fallback_source is used as the source when metadata has no 'category' key."""
        from plugins.builtin.gallery_dl._metadata import parse_gallery_dl_import

        meta = {
            "tweet_id": 3333333333,
            "author": {"name": "no_category_artist"},
        }
        result = parse_gallery_dl_import(tmp_path, meta, fallback_source="twitter")
        assert result.source == "twitter"

    def test_parse_import_fallback_source_resolves_source_id_fields(self, tmp_path: Path):
        """When using fallback_source, source_id_fields from that config are used."""
        from plugins.builtin.gallery_dl._metadata import parse_gallery_dl_import

        meta = {
            # No "category" — twitter's source_id_fields=("tweet_id",)
            "tweet_id": 4444444444,
            "author": {"name": "artist_x"},
        }
        result = parse_gallery_dl_import(tmp_path, meta, fallback_source="twitter")
        assert result.source_id == "4444444444"

    def test_parse_import_no_category_no_fallback_uses_gallery_dl(self, tmp_path: Path):
        """Without category or fallback_source, source defaults to 'gallery_dl'."""
        from plugins.builtin.gallery_dl._metadata import parse_gallery_dl_import

        named_dir = tmp_path / "some_download_dir"
        named_dir.mkdir()

        meta = {"title": "A Generic Download"}
        result = parse_gallery_dl_import(named_dir, meta)
        assert result.source == "gallery_dl"

    def test_parse_import_category_takes_precedence_over_fallback(self, tmp_path: Path):
        """When metadata has 'category', it overrides fallback_source."""
        from plugins.builtin.gallery_dl._metadata import parse_gallery_dl_import

        meta = {
            "category": "danbooru",
            "id": 66666,
        }
        result = parse_gallery_dl_import(tmp_path, meta, fallback_source="twitter")
        assert result.source == "danbooru"

    def test_parse_import_empty_meta_reads_json_from_dir(self, tmp_path: Path):
        """With no raw_meta provided, parse_gallery_dl_import reads JSON files from dest_dir."""
        import json
        from plugins.builtin.gallery_dl._metadata import parse_gallery_dl_import

        gallery_dir = tmp_path / "gallery_123"
        gallery_dir.mkdir()
        meta_file = gallery_dir / "info.json"
        meta_file.write_text(json.dumps({
            "category": "twitter",
            "tweet_id": 5555555555,
            "author": {"name": "json_file_artist"},
        }), encoding="utf-8")

        result = parse_gallery_dl_import(gallery_dir)
        assert result.source == "twitter"
        assert result.source_id == "5555555555"
        assert result.title == "json_file_artist"


# ---------------------------------------------------------------------------
# _extract_tags (gallery_dl._metadata) — hashtag extraction
# ---------------------------------------------------------------------------


class TestExtractTagsHashtags:
    """_extract_tags extracts hashtags from content for social sources."""

    def test_extract_tags_social_source_extracts_hashtags(self):
        """content field with hashtags on a social source yields 'general:<tag>' entries."""
        from plugins.builtin.gallery_dl._metadata import _extract_tags

        metadata = {"content": "#cosplay #anime test"}
        tags = _extract_tags(Path("/tmp/test"), metadata, source="twitter")
        assert "general:cosplay" in tags
        assert "general:anime" in tags

    def test_extract_tags_non_social_source_ignores_hashtags(self):
        """Hashtags in content are NOT extracted for non-social sources (e.g. ehentai)."""
        from plugins.builtin.gallery_dl._metadata import _extract_tags

        metadata = {"content": "#cosplay #anime test", "category": "gallery"}
        tags = _extract_tags(Path("/tmp/test"), metadata, source="ehentai")
        assert "general:cosplay" not in tags
        assert "general:anime" not in tags

    def test_extract_tags_no_source_ignores_hashtags(self):
        """When source=None, hashtag extraction is skipped entirely."""
        from plugins.builtin.gallery_dl._metadata import _extract_tags

        metadata = {"content": "#sketch #artwork"}
        tags = _extract_tags(Path("/tmp/test"), metadata, source=None)
        assert "general:sketch" not in tags
        assert "general:artwork" not in tags

    def test_extract_tags_hashtag_dedup_with_existing(self):
        """A hashtag matching an already-present tag is not duplicated."""
        from plugins.builtin.gallery_dl._metadata import _extract_tags

        metadata = {"tags": ["general:cosplay"], "content": "#cosplay #anime"}
        tags = _extract_tags(Path("/tmp/test"), metadata, source="twitter")
        assert tags.count("general:cosplay") == 1
        assert "general:anime" in tags

    def test_extract_tags_hashtag_from_description_field(self):
        """When 'content' is absent, hashtags are extracted from 'description'."""
        from plugins.builtin.gallery_dl._metadata import _extract_tags

        metadata = {"description": "#sketch"}
        tags = _extract_tags(Path("/tmp/test"), metadata, source="twitter")
        assert "general:sketch" in tags

    def test_extract_tags_hashtag_lowercased(self):
        """Hashtag text is lowercased before building the tag string."""
        from plugins.builtin.gallery_dl._metadata import _extract_tags

        metadata = {"content": "#CosPlay"}
        tags = _extract_tags(Path("/tmp/test"), metadata, source="twitter")
        assert "general:cosplay" in tags
        assert "general:CosPlay" not in tags


# ---------------------------------------------------------------------------
# _extract_artist (gallery_dl._metadata)
# ---------------------------------------------------------------------------


class TestExtractArtistPixivUser:
    """_extract_artist handles pixiv_user strategy and twitter_author strategy."""

    def test_extract_artist_pixiv_user_with_user_id(self):
        """pixiv source with pixiv_user_id produces 'pixiv:<id>'."""
        from plugins.builtin.gallery_dl._metadata import _extract_artist

        result = _extract_artist("pixiv", {"pixiv_user_id": 12345, "uploader": "someone"}, [])
        assert result == "pixiv:12345"

    def test_extract_artist_pixiv_user_fallback_to_uploader(self):
        """pixiv source without pixiv_user_id falls back to 'pixiv:<uploader>'."""
        from plugins.builtin.gallery_dl._metadata import _extract_artist

        result = _extract_artist("pixiv", {"uploader": "someone"}, [])
        assert result == "pixiv:someone"

    def test_extract_artist_pixiv_user_no_data(self):
        """pixiv source with no pixiv_user_id and no uploader returns None."""
        from plugins.builtin.gallery_dl._metadata import _extract_artist

        result = _extract_artist("pixiv", {}, [])
        assert result is None

    def test_extract_artist_twitter_still_works(self):
        """twitter source extracts artist from author.name dict (existing behavior)."""
        from plugins.builtin.gallery_dl._metadata import _extract_artist

        result = _extract_artist("twitter", {"author": {"name": "alice"}}, [])
        assert result == "twitter:alice"


# ---------------------------------------------------------------------------
# parse_pixiv_import — artist_id extraction
# ---------------------------------------------------------------------------


class TestParsePixivImportArtistId:
    """parse_pixiv_import resolves artist_id with priority: pixiv_user_id > uploader > None."""

    def test_parse_pixiv_import_artist_id_from_user_id(self):
        """pixiv_user_id in meta → artist_id == 'pixiv:<user_id>'."""
        from plugins.builtin.pixiv._metadata import parse_pixiv_import

        meta = {"pixiv_user_id": 12345, "uploader": "name", "id": 99}
        result = parse_pixiv_import(Path("/tmp/test"), meta)
        assert result.artist_id == "pixiv:12345"

    def test_parse_pixiv_import_artist_id_fallback_uploader(self):
        """No pixiv_user_id but uploader present → artist_id == 'pixiv:<uploader>'."""
        from plugins.builtin.pixiv._metadata import parse_pixiv_import

        meta = {"uploader": "name", "id": 99}
        result = parse_pixiv_import(Path("/tmp/test"), meta)
        assert result.artist_id == "pixiv:name"

    def test_parse_pixiv_import_artist_id_none(self):
        """No pixiv_user_id and no uploader → artist_id is None."""
        from plugins.builtin.pixiv._metadata import parse_pixiv_import

        meta = {"id": 99}
        result = parse_pixiv_import(Path("/tmp/test"), meta)
        assert result.artist_id is None
