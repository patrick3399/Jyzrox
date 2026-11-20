"""Field-level analysis of gallery-dl probe output (see ``core.probe``)."""

import json
import logging
import re
from dataclasses import dataclass

from core.site_config import JYZROX_FIELDS

logger = logging.getLogger(__name__)

# Maximum length for a single string field value in probe output.
_MAX_FIELD_VALUE_LEN = 10_240

# Gallery-dl internal fields to exclude from analysis.
_SKIP_FIELD_PREFIXES = ("_",)
_SKIP_FIELDS = frozenset({"category", "subcategory"})

# Scoring table: jyzrox_field → list of (key_hint, score_boost)
# Exact key matches earn 0.9; partial matches 0.7; type-only matches 0.3.
_ROLE_HINTS: dict[str, list[tuple[str, float]]] = {
    "source_id": [("gallery_id", 0.9), ("id", 0.7)],
    "title": [("title", 0.9), ("title_en", 0.7), ("description", 0.5), ("content", 0.4)],
    "artist": [("uploader", 0.9), ("username", 0.7), ("author", 0.7)],
    "tags": [("tags", 0.9)],
    "date": [("date", 0.9), ("posted", 0.7)],
    "title_jpn": [("title_jpn", 0.9), ("title_original", 0.7)],
    "category": [("gallery_category", 0.9), ("category", 0.7)],
    "language": [("lang", 0.9), ("language", 0.7)],
    "uploader": [("uploader", 0.9), ("username", 0.7)],
}

# Guard: all _ROLE_HINTS keys must be valid Jyzrox canonical field names.
assert frozenset(_ROLE_HINTS) <= JYZROX_FIELDS, (
    f"_ROLE_HINTS contains unknown Jyzrox fields: {frozenset(_ROLE_HINTS) - JYZROX_FIELDS}"
)

# Preferred field types per Jyzrox role.
_ROLE_PREFERRED_TYPES: dict[str, frozenset[str]] = {
    "source_id": frozenset({"numeric_id", "text"}),
    "title": frozenset({"text"}),
    "artist": frozenset({"text"}),
    "tags": frozenset({"namespaced_tags", "flat_tags"}),
    "date": frozenset({"datetime", "timestamp"}),
    "title_jpn": frozenset({"text"}),
    "category": frozenset({"text"}),
    "language": frozenset({"text"}),
    "uploader": frozenset({"text"}),
}

# ISO 8601 / common date patterns.
_DATE_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}"  # YYYY-MM-DD
    r"([ T]\d{2}:\d{2}(:\d{2})?([+-]\d{2}:?\d{2}|Z)?)?"  # optional time
    r"$"
)


@dataclass
class ProbeField:
    key: str
    field_type: str  # url/datetime/timestamp/namespaced_tags/flat_tags/numeric_id/text
    sample_value: str
    level: str  # "gallery" or "page"


@dataclass
class FieldMapping:
    jyzrox_field: str
    gdl_field: str | None  # None = unmapped
    confidence: float
    suggested: bool


def _validate_probe_output(raw: list[dict]) -> list[dict]:
    """Truncate any string fields longer than 10 KB to prevent UI bloat."""
    cleaned: list[dict] = []
    for item in raw:
        new_item: dict = {}
        for key, val in item.items():
            if isinstance(val, str) and len(val) > _MAX_FIELD_VALUE_LEN:
                new_item[key] = val[:_MAX_FIELD_VALUE_LEN] + "..."
            else:
                new_item[key] = val
        cleaned.append(new_item)
    return cleaned


def _diff_fields(items: list[dict]) -> list[ProbeField]:
    """Classify each field as gallery-level (constant) or page-level (varies).

    Skips internal fields (starting with '_') and category/subcategory.
    """
    if not items:
        return []

    # Collect all field keys across items.
    all_keys: set[str] = set()
    for item in items:
        all_keys.update(item.keys())

    result: list[ProbeField] = []
    for key in sorted(all_keys):
        if key in _SKIP_FIELDS:
            continue
        if any(key.startswith(p) for p in _SKIP_FIELD_PREFIXES):
            continue

        # Gather values for this key across all items.
        values = [item[key] for item in items if key in item]
        if not values:
            continue

        # Determine gallery vs page level.
        # Use string representation for comparison to handle unhashable types.
        str_values = [json.dumps(v, sort_keys=True, default=str) for v in values]
        level = "gallery" if len(set(str_values)) == 1 else "page"

        field_type = _fingerprint_field(key, values)

        # Build a concise sample value for UI display.
        sample_raw = values[0]
        if isinstance(sample_raw, dict | list):
            sample = json.dumps(sample_raw, ensure_ascii=False)[:200]
        else:
            sample = str(sample_raw)[:200]

        result.append(ProbeField(key=key, field_type=field_type, sample_value=sample, level=level))

    return result


def _fingerprint_field(_key: str, values: list) -> str:
    """Infer the semantic type of a field from its values."""
    # Use the first non-None value for type detection.
    sample = next((v for v in values if v is not None), None)
    if sample is None:
        return "text"

    if isinstance(sample, dict):
        # namespaced_tags: dict with string keys mapping to lists of strings.
        if all(isinstance(v, list) for v in sample.values()):
            return "namespaced_tags"
        return "text"

    if isinstance(sample, list):
        if all(isinstance(el, str) for el in sample):
            return "flat_tags"
        return "text"

    if isinstance(sample, bool):
        return "text"

    if isinstance(sample, int):
        if sample > 1_000_000_000:
            return "timestamp"
        return "numeric_id"

    if isinstance(sample, float):
        if sample > 1_000_000_000.0:
            return "timestamp"
        return "text"

    if isinstance(sample, str):
        if sample.startswith("http://") or sample.startswith("https://"):
            return "url"
        if _DATE_RE.match(sample.strip()):
            return "datetime"
        if sample.isdigit():
            return "numeric_id"
        return "text"

    return "text"


def _score_mappings(fields: list[ProbeField], _items: list[dict]) -> list[FieldMapping]:
    """For each Jyzrox canonical field, find the best-matching gallery-dl field.

    Scoring rules:
    - Exact key match: 0.9
    - Partial key match (hint is substring of key or vice versa): 0.7
    - Type-only match (no key hint): 0.3
    Only includes mappings with confidence >= 0.3.
    """
    field_by_key = {f.key: f for f in fields}
    # Per design spec: only gallery-level fields are mapping candidates.
    gallery_fields = {k: f for k, f in field_by_key.items() if f.level == "gallery"}
    mappings: list[FieldMapping] = []

    for jyzrox_role, hints in _ROLE_HINTS.items():
        preferred_types = _ROLE_PREFERRED_TYPES.get(jyzrox_role, frozenset())

        best_key: str | None = None
        best_score: float = 0.0

        for gdl_field, probe_field in gallery_fields.items():
            # source_id "id" hint only counts if type is numeric_id.
            score = 0.0
            for hint, hint_score in hints:
                if gdl_field == hint:
                    if hint == "id" and jyzrox_role == "source_id" and probe_field.field_type != "numeric_id":
                        continue
                    score = max(score, hint_score)
                elif hint in gdl_field or gdl_field in hint:
                    score = max(score, 0.7)

            # Type-only boost when no key hint matched.
            if score == 0.0 and probe_field.field_type in preferred_types:
                score = 0.3
            elif score > 0.0 and probe_field.field_type in preferred_types:
                # Small bonus for correct type.
                score = min(1.0, score + 0.05)

            if score > best_score:
                best_score = score
                best_key = gdl_field

        if best_score >= 0.3 and best_key is not None:
            mappings.append(
                FieldMapping(
                    jyzrox_field=jyzrox_role,
                    gdl_field=best_key,
                    confidence=round(best_score, 3),
                    suggested=True,
                )
            )
        else:
            # Include unmapped entries so callers know the field is unresolved.
            mappings.append(
                FieldMapping(
                    jyzrox_field=jyzrox_role,
                    gdl_field=None,
                    confidence=0.0,
                    suggested=False,
                )
            )

    return mappings


def _detect_source(raw: list[dict]) -> str | None:
    """Detect the gallery-dl source_id by matching 'category' in the site registry."""
    if not raw:
        return None

    gdl_category = raw[0].get("category")
    if not gdl_category:
        return None

    from plugins.builtin.gallery_dl._sites import all_sites

    gdl_category_lower = str(gdl_category).lower()
    for site in all_sites():
        # gallery-dl 'category' field typically matches the extractor name.
        extractor_name = site.extractor or site.source_id
        if extractor_name.lower() == gdl_category_lower or site.source_id.lower() == gdl_category_lower:
            return site.source_id

    return None
