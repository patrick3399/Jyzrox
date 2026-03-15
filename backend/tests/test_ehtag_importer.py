"""Tests for EhTagTranslation CDN importer parsing logic."""

import pytest

from services.ehtag_importer import parse_ehtag_payload


class TestParseEhtagPayload:
    """parse_ehtag_payload extracts translation rows from CDN JSON."""

    def test_valid_namespace_extracted(self):
        """Tags in valid namespaces are extracted."""
        payload = {
            "data": [
                {
                    "namespace": "artist",
                    "data": {
                        "bob": {"name": "鮑伯", "intro": "", "links": ""},
                    },
                }
            ]
        }
        rows = parse_ehtag_payload(payload)
        assert len(rows) == 1
        assert rows[0] == {
            "namespace": "artist",
            "name": "bob",
            "language": "zh",
            "translation": "鮑伯",
        }

    def test_rows_namespace_skipped(self):
        """The 'rows' namespace (metadata) is skipped."""
        payload = {
            "data": [
                {
                    "namespace": "rows",
                    "data": {"something": {"name": "meta"}},
                }
            ]
        }
        rows = parse_ehtag_payload(payload)
        assert len(rows) == 0

    def test_unknown_namespace_skipped(self):
        """Unknown namespaces not in _VALID_NAMESPACES are skipped."""
        payload = {
            "data": [
                {
                    "namespace": "unknown_ns",
                    "data": {"tag1": {"name": "翻譯"}},
                }
            ]
        }
        rows = parse_ehtag_payload(payload)
        assert len(rows) == 0

    def test_empty_tag_name_skipped(self):
        """Tags with empty key are skipped."""
        payload = {
            "data": [
                {
                    "namespace": "misc",
                    "data": {"": {"name": "空"}},
                }
            ]
        }
        rows = parse_ehtag_payload(payload)
        assert len(rows) == 0

    def test_non_dict_tag_info_skipped(self):
        """Tags where info is not a dict are skipped."""
        payload = {
            "data": [
                {
                    "namespace": "misc",
                    "data": {"tag1": "not a dict"},
                }
            ]
        }
        rows = parse_ehtag_payload(payload)
        assert len(rows) == 0

    def test_empty_translation_skipped(self):
        """Tags with empty 'name' (translation) field are skipped."""
        payload = {
            "data": [
                {
                    "namespace": "misc",
                    "data": {"tag1": {"name": "", "intro": "x"}},
                }
            ]
        }
        rows = parse_ehtag_payload(payload)
        assert len(rows) == 0

    def test_multiple_namespaces(self):
        """Tags from multiple valid namespaces are all extracted."""
        payload = {
            "data": [
                {
                    "namespace": "artist",
                    "data": {"alice": {"name": "愛麗絲"}},
                },
                {
                    "namespace": "character",
                    "data": {"rem": {"name": "雷姆"}},
                },
                {
                    "namespace": "female",
                    "data": {"cat ears": {"name": "貓耳"}},
                },
            ]
        }
        rows = parse_ehtag_payload(payload)
        assert len(rows) == 3
        namespaces = {r["namespace"] for r in rows}
        assert namespaces == {"artist", "character", "female"}

    def test_all_valid_namespaces_accepted(self):
        """All 12 valid namespaces are accepted."""
        valid = [
            "artist", "character", "parody", "group", "language",
            "misc", "other", "reclass", "cosplayer",
            "female", "male", "mixed",
        ]
        payload = {
            "data": [
                {"namespace": ns, "data": {"tag": {"name": f"翻譯_{ns}"}}}
                for ns in valid
            ]
        }
        rows = parse_ehtag_payload(payload)
        assert len(rows) == 12

    def test_empty_payload_returns_empty(self):
        """Empty payload returns empty list."""
        assert parse_ehtag_payload({}) == []
        assert parse_ehtag_payload({"data": []}) == []

    def test_multiple_tags_in_one_namespace(self):
        """Multiple tags within one namespace are all extracted."""
        payload = {
            "data": [
                {
                    "namespace": "misc",
                    "data": {
                        "tag_a": {"name": "翻譯A"},
                        "tag_b": {"name": "翻譯B"},
                        "tag_c": {"name": "翻譯C"},
                    },
                }
            ]
        }
        rows = parse_ehtag_payload(payload)
        assert len(rows) == 3

    def test_language_always_zh(self):
        """All rows have language='zh'."""
        payload = {
            "data": [
                {
                    "namespace": "artist",
                    "data": {"x": {"name": "翻譯"}},
                }
            ]
        }
        rows = parse_ehtag_payload(payload)
        assert all(r["language"] == "zh" for r in rows)
