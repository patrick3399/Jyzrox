"""Helpers for local library path patterns."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path


DEFAULT_LIBRARY_PATTERN = "{title}"
DEFAULT_IMPORT_MODE = "link"
_PLACEHOLDER_RE = re.compile(r"\{([^}]+)\}")


@dataclass(frozen=True)
class ParsedLibraryPattern:
    root_path: str
    pattern: str
    display_pattern: str


class PatternError(ValueError):
    pass


def normalize_relative_path(path: str) -> str:
    return path.replace(os.sep, "/").strip("/")


def split_library_pattern_path(path: str) -> ParsedLibraryPattern:
    """Split a user-entered library path into root and relative pattern."""
    raw = path.strip()
    first_placeholder = raw.find("{")
    if first_placeholder == -1:
        root_path = os.path.realpath(raw)
        pattern = DEFAULT_LIBRARY_PATTERN
    else:
        static_prefix = raw[:first_placeholder]
        root_part = static_prefix.rstrip("/\\")
        pattern_part = raw[len(root_part) :].lstrip("/\\")
        root_path = os.path.realpath(root_part or os.sep)
        pattern = normalize_relative_path(pattern_part)

    validate_library_pattern(pattern)
    return ParsedLibraryPattern(
        root_path=root_path,
        pattern=pattern,
        display_pattern=display_library_pattern(root_path, pattern),
    )


def display_library_pattern(root_path: str, pattern: str | None) -> str:
    pattern = normalize_relative_path(pattern or DEFAULT_LIBRARY_PATTERN)
    return f"{root_path.rstrip('/')}/{pattern}" if pattern else root_path


def validate_library_pattern(pattern: str) -> None:
    pattern = normalize_relative_path(pattern)
    if not pattern:
        raise PatternError("Pattern cannot be empty")
    if len(pattern) > 500:
        raise PatternError("Pattern too long")
    if "{title}" not in pattern:
        raise PatternError("Pattern must include {title}")

    seen: set[str] = set()
    for match in _PLACEHOLDER_RE.finditer(pattern):
        name = match.group(1)
        if name != "_" and not re.fullmatch(r"[a-zA-Z_]\w*", name):
            raise PatternError(f"Invalid placeholder name: {{{name}}}")
        if name != "_":
            if name in seen:
                raise PatternError(f"Duplicate placeholder name: {{{name}}}")
            seen.add(name)

    rebuilt = "".join(_PLACEHOLDER_RE.split(pattern)[::2])
    if "{" in rebuilt or "}" in rebuilt:
        raise PatternError("Invalid placeholder syntax")


def build_library_pattern_regex(pattern: str) -> re.Pattern[str]:
    validate_library_pattern(pattern)
    parts = re.split(r"(\{[^}]+\})", normalize_relative_path(pattern))
    regex_parts: list[str] = []
    for part in parts:
        if part.startswith("{") and part.endswith("}"):
            name = part[1:-1]
            if name == "_":
                regex_parts.append(r"(?:[^/]+)")
            else:
                regex_parts.append(rf"(?P<{name}>[^/]+)")
        else:
            regex_parts.append(re.escape(part))
    return re.compile("^" + "".join(regex_parts) + "$")


def pattern_match(pattern: str, root: Path, candidate: Path) -> dict[str, str] | None:
    try:
        rel_path = normalize_relative_path(str(candidate.relative_to(root)))
    except ValueError:
        return None
    match = build_library_pattern_regex(pattern).match(rel_path)
    return match.groupdict() if match else None
