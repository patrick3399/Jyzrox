"""Shared Pixiv tag processing utilities."""


def process_pixiv_tags(detail: dict) -> tuple[list[str], list[dict]]:
    """Extract, deduplicate, and auto-tag from Pixiv API detail.

    Processes the ``tags`` list from a Pixiv illust detail dict:
    - For dict tags: prefers ``translated_name`` (English) over ``name``
      (Japanese), deduplicates case-insensitively.
    - For string tags: deduplicates case-insensitively.
    - Records Japanese translations for dict tags that have both fields.
    - Auto-appends ``rating:r18`` when ``sanity_level >= 6``.
    - Auto-appends ``meta:manga`` or ``meta:ugoira`` based on ``type``.

    Args:
        detail: Normalised Pixiv illust detail dict as returned by PixivClient.

    Returns:
        A tuple of ``(tag_list, tag_translations_data)`` where:
        - ``tag_list`` is a deduplicated list of canonical tag strings.
        - ``tag_translations_data`` is a list of translation dicts suitable
          for the tag_translations import field.
    """
    tags = detail.get("tags", [])
    tag_list: list[str] = []
    tag_translations_data: list[dict] = []
    seen_tags: set[str] = set()

    for tag in tags:
        if isinstance(tag, dict):
            name = tag.get("name", "")
            translated = tag.get("translated_name")
            # Prefer English (translated_name) over Japanese (name)
            canonical = translated if translated else name
            if canonical and canonical.lower() not in seen_tags:
                tag_list.append(canonical)
                seen_tags.add(canonical.lower())
            # Store Japanese as translation
            if name and translated and name != translated:
                tag_translations_data.append({
                    "namespace": "general",
                    "name": translated,
                    "language": "ja",
                    "translation": name,
                })
        elif isinstance(tag, str) and tag.lower() not in seen_tags:
            tag_list.append(tag)
            seen_tags.add(tag.lower())

    # Auto-tag: rating from sanity_level
    sanity = detail.get("sanity_level", 0)
    if sanity >= 8 and "rating:r18g" not in seen_tags:
        tag_list.append("rating:r18g")
    elif sanity >= 6 and "rating:r18" not in seen_tags:
        tag_list.append("rating:r18")

    # Auto-tag: illust type
    illust_type = detail.get("type", "illust")
    if illust_type == "manga":
        tag_list.append("meta:manga")
    elif illust_type == "ugoira":
        tag_list.append("meta:ugoira")

    return tag_list, tag_translations_data
