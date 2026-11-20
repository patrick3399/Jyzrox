"""gallery-dl credential fragments and metadata field list."""

import json

# Fields included in the metadata postprocessor JSON output.
_METADATA_INCLUDE = (
    "category",
    "subcategory",
    "title",
    "title_en",
    "title_jpn",
    "tags",
    "tag_string",
    "description",
    "id",
    "gallery_id",
    "uploader",
    "user",
    "artist",
    "date",
    "posted_at",
    "count",
    "num",
    "rating",
    "language",
    "author",
    "username",
    "user_id",
    "content",
)


def _metadata_include() -> list[str]:
    """_METADATA_INCLUDE plus the fields drop-in extractors declared (JYZROX_SITE)."""
    from plugins.builtin.gallery_dl._sites import extra_metadata_fields

    return list(dict.fromkeys([*_METADATA_INCLUDE, *extra_metadata_fields()]))


FRAGMENT_KEYS = {"cookies", "username", "password", "refresh-token", "api-key"}


def _try_parse_fragment(cred_val: str) -> dict | None:
    """Try to parse a credential value as a gallery-dl config fragment (new format).

    Returns the parsed dict if it's a fragment, None otherwise.
    """
    try:
        parsed = json.loads(cred_val)
        if isinstance(parsed, dict) and (FRAGMENT_KEYS & parsed.keys()):
            return parsed
    except json.JSONDecodeError, TypeError:
        pass
    return None


def _is_fragment(cred_val: str) -> bool:
    """Check if a credential value is a gallery-dl config fragment (new format)."""
    return _try_parse_fragment(cred_val) is not None
