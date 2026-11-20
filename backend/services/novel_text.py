"""Act and wikilink extraction from novel markdown."""

from __future__ import annotations

import re

_WIKILINK = re.compile(r"\[\[([^\]|#]+)")
_ACT = re.compile(r"^### +(.*)$")


def parse_acts(content: str) -> list[dict]:
    acts: list[dict] = []
    for lineno, line in enumerate(content.splitlines()):
        m = _ACT.match(line)
        if m:
            acts.append({"index": len(acts), "title": m.group(1).strip(), "line": lineno})
    return acts


def parse_backlinks(content: str) -> list[str]:
    seen: list[str] = []
    for m in _WIKILINK.finditer(content):
        name = m.group(1).strip()
        if name and name not in seen:
            seen.append(name)
    return seen
