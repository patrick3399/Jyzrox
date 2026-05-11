"""Helpers for local library path patterns."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

DEFAULT_LIBRARY_PATTERN = "{title}"
DEFAULT_IMPORT_MODE = "link"


@dataclass(frozen=True)
class ParsedLibraryPattern:
    root_path: str
    pattern: str
    display_pattern: str


class PatternError(ValueError):
    pass


class LibraryPatternMatch:
    def __init__(self, groups: dict[str, str]) -> None:
        self._groups = groups

    def groupdict(self) -> dict[str, str]:
        return dict(self._groups)


class LibraryPatternRegex:
    """Regex-like matcher for validated library path patterns."""

    def __init__(self, tokens: list[tuple[str, str]], pattern: str) -> None:
        self._tokens = tokens
        self.pattern = pattern

    def match(self, value: str) -> LibraryPatternMatch | None:
        normalized = normalize_relative_path(value)
        groups = self._match_from(0, 0, normalized, {})
        return LibraryPatternMatch(groups) if groups is not None else None

    def _match_from(
        self,
        token_index: int,
        value_index: int,
        value: str,
        groups: dict[str, str],
    ) -> dict[str, str] | None:
        if token_index == len(self._tokens):
            return groups if value_index == len(value) else None

        kind, token_value = self._tokens[token_index]
        if kind == "literal":
            if not value.startswith(token_value, value_index):
                return None
            return self._match_from(token_index + 1, value_index + len(token_value), value, groups)

        segment_end = value.find("/", value_index)
        max_end = len(value) if segment_end == -1 else segment_end
        if value_index >= max_end:
            return None

        for end in range(value_index + 1, max_end + 1):
            next_groups = dict(groups)
            if token_value != "_":
                next_groups[token_value] = value[value_index:end]
            matched = self._match_from(token_index + 1, end, value, next_groups)
            if matched is not None:
                return matched
        return None


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
    has_title = False
    for kind, value in _iter_pattern_tokens(pattern):
        if kind != "placeholder":
            continue
        name = value
        if name == "title":
            has_title = True
        if name != "_" and not _is_valid_placeholder_name(name):
            raise PatternError(f"Invalid placeholder name: {{{name}}}")
        if name != "_":
            if name in seen:
                raise PatternError(f"Duplicate placeholder name: {{{name}}}")
            seen.add(name)

    if not has_title:
        raise PatternError("Pattern must include {title}")


def build_library_pattern_regex(pattern: str) -> LibraryPatternRegex:
    validate_library_pattern(pattern)
    tokens = _iter_pattern_tokens(normalize_relative_path(pattern))
    pattern_parts: list[str] = []
    for kind, value in tokens:
        if kind == "placeholder":
            name = value
            if name == "_":
                pattern_parts.append(r"(?:[^/]+)")
            else:
                pattern_parts.append(rf"(?P<{name}>[^/]+)")
        else:
            pattern_parts.append(_regex_display_escape(value))
    return LibraryPatternRegex(tokens, "^" + "".join(pattern_parts) + "$")


def _is_valid_placeholder_name(name: str) -> bool:
    if not name:
        return False
    first = name[0]
    if not (first == "_" or "A" <= first <= "Z" or "a" <= first <= "z"):
        return False
    return all(ch == "_" or "A" <= ch <= "Z" or "a" <= ch <= "z" or "0" <= ch <= "9" for ch in name[1:])


def _regex_display_escape(value: str) -> str:
    special = frozenset(r"\.^$*+?{}[]|()")
    return "".join(f"\\{ch}" if ch in special else ch for ch in value)


def _iter_pattern_tokens(pattern: str) -> list[tuple[Literal["literal", "placeholder"], str]]:
    """Tokenize a library pattern with linear brace parsing."""
    tokens: list[tuple[Literal["literal", "placeholder"], str]] = []
    literal_start = 0
    index = 0
    length = len(pattern)

    while index < length:
        char = pattern[index]
        if char == "}":
            raise PatternError("Invalid placeholder syntax")
        if char != "{":
            index += 1
            continue

        if literal_start < index:
            tokens.append(("literal", pattern[literal_start:index]))
        close_index = pattern.find("}", index + 1)
        if close_index == -1:
            raise PatternError("Invalid placeholder syntax")
        name = pattern[index + 1 : close_index]
        if "{" in name or "}" in name:
            raise PatternError("Invalid placeholder syntax")
        tokens.append(("placeholder", name))
        index = close_index + 1
        literal_start = index

    if literal_start < length:
        tokens.append(("literal", pattern[literal_start:]))
    return tokens


def pattern_match(pattern: str, root: Path, candidate: Path) -> dict[str, str] | None:
    try:
        rel_path = normalize_relative_path(str(candidate.relative_to(root)))
    except ValueError:
        return None
    match = build_library_pattern_regex(pattern).match(rel_path)
    return match.groupdict() if match else None
