"""YAML frontmatter parsing and editing for novel markdown files."""

from __future__ import annotations


def parse_frontmatter(content: str) -> tuple[dict, str]:
    """Split leading YAML frontmatter from the markdown body.

    Tolerant by design (§4.5.8): no fence → ({}, content); malformed YAML →
    ({}, body). Never raises — old notes without frontmatter must index cleanly.
    """
    if not content.startswith("---\n"):
        return {}, content
    end = content.find("\n---", 4)
    if end == -1:
        return {}, content
    raw = content[4:end]
    body = content[end + 4 :].lstrip("\n")
    try:
        import yaml

        data = yaml.safe_load(raw)
    except Exception:  # noqa: BLE001 — malformed frontmatter is tolerated
        return {}, body
    return (data if isinstance(data, dict) else {}), body


def _yaml_line(key: str, value: str) -> str:
    import yaml

    # width high enough that a long summary is never folded across lines: the
    # upsert below is line-oriented and a folded value would corrupt the fence.
    return yaml.safe_dump({key: value}, allow_unicode=True, width=10**6, sort_keys=False).rstrip("\n")


def _node_end(lines: list[str], start: int) -> int:
    """Index just past the top-level YAML node that begins at ``lines[start]``.

    A key's value is not always one line: block and folded scalars (`|`, `>`),
    multi-line flow collections, and wrapped quoted scalars all continue on
    more-indented lines. Removing only the `key:` line orphaned those
    continuations, and YAML then absorbed them into the *previous* key (silently
    rewriting it) or failed to parse the fence at all — in which case
    ``parse_frontmatter`` tolerates the error and returns ``{}``, losing every
    field without a word.

    Interior blank lines are claimed only when a further indented line follows,
    so a blank separating two top-level keys stays where the author put it.
    """
    i = start + 1
    claimed = i
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if line[:1].isspace():
            i += 1
            claimed = i
            continue
        break
    return claimed


def set_frontmatter_value(content: str, key: str, value: str | None) -> str:
    """Insert/replace/remove one scalar key in the leading YAML frontmatter.

    Line-oriented on purpose: a YAML round-trip would reformat hand-written
    notes (quoting, key order, comments), and these files are edited on the
    desktop too. Everything outside the key's own node is preserved byte for
    byte. `value=None` (or blank) removes the key, and drops the fence entirely
    once it holds nothing else.
    """
    text = " ".join(value.split()) if value else ""
    has_fence = content.startswith("---\n")
    end = content.find("\n---", 4) if has_fence else -1
    if end == -1:
        if not text:
            return content
        return f"---\n{_yaml_line(key, text)}\n---\n\n{content}"

    head_lines = content[4:end].split("\n")
    rest = content[end + 4 :]
    prefix = f"{key}:"
    kept: list[str] = []
    idx = 0
    while idx < len(head_lines):
        # Only a column-0 `key:` is this document's own field; an indented match
        # belongs to some nested mapping and must be left alone.
        if head_lines[idx].startswith(prefix):
            idx = _node_end(head_lines, idx)
            continue
        kept.append(head_lines[idx])
        idx += 1
    if text:
        kept.append(_yaml_line(key, text))
    if not [ln for ln in kept if ln.strip()]:
        # The fence existed only for this key — remove it, and the blank line
        # that separated it from the body, so removal is a clean undo of insert.
        return rest.lstrip("\n")
    return "---\n" + "\n".join(kept) + "\n---" + rest
