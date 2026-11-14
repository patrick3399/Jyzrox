"""FORMAT.md conformance: lint + auto-fix for novel markdown.

The same rules run on the server (behind the API) and on the desktop: the novel
repo keeps a verbatim copy of this file at `tools/novel_format.py`, used by its
`check_format.py` / `fix_format.py`. Update the copy whenever this file changes
— the same chapter must not lint differently depending on where it was checked.
Pure text in / findings out — no git, no DB, no filesystem, stdlib only.

Rules are identified by stable snake_case ids; the UI owns their wording (i18n).
"""

from __future__ import annotations

import re

_ACT_NAME = r"(?:第[一二三四五六七八九十百]+幕|序幕|終幕)"
_CHAPTER_NO = r"第[\d一二三四五六七八九十百]+章"

# Line-level checks: (rule id, compiled pattern, match-not-search). The chapter
# title is checked separately: only the first prose line is the title, and a
# chapter may legitimately use `### 第一章：…` headings for its own sections.
_LINE_RULES: list[tuple[str, re.Pattern[str], bool]] = [
    # 幕標題混入章編號：第N章 第N幕（行首；`（第六章 第四幕 完）` 這類幕尾標記不算）
    ("act_title_has_chapter_number", re.compile(rf"^(?:#{{1,6}}\s+)?{_CHAPTER_NO}\s+{_ACT_NAME}[：:]"), True),
    # 幕標題層級錯誤：#### 第N幕
    ("act_title_wrong_level", re.compile(rf"^####\s+{_ACT_NAME}[：:]"), True),
    # 幕標題用粗體替代標題
    ("act_title_bold_instead_of_heading", re.compile(rf"^\*\*{_ACT_NAME}[：:]"), True),
    # 幕標題寫成 **【第N幕：…】**
    ("act_title_bracket_bold", re.compile(rf"^\*\*【{_ACT_NAME}[：:]"), True),
    # ### **第N幕** 多餘粗體
    ("act_title_redundant_bold", re.compile(rf"^###\s+\*\*{_ACT_NAME}"), True),
    # 對話冒號在粗體外：**角色名**：「
    ("dialogue_colon_outside_bold", re.compile(r"\*\*[^*【]+\*\*\s*[：:]「"), False),
    # 結尾標記用半形括號
    ("halfwidth_paren_marker", re.compile(r"\(第[一二三四五六七八九十百\d]+(?:章|幕|部)"), False),
]

_META_FIELDS = ("地點", "時間", "人物", "主要人物", "狀態")
_META_COLON_OUTSIDE = [re.compile(rf"\*\*{f}\*\*\s*[：:]") for f in _META_FIELDS]

# The 裏側視角 heading must sit outside the blockquote it introduces.
_INNER_VIEW = re.compile(r"^>\s*\*\*【裏側視角")
_CHAPTER_END = re.compile(r"（.{1,20}完）\s*$")
# A chapter's first line: `第N章` alone or `第N章：標題` — plain, or decorated
# with a heading marker or bold (both fixable).
_CHAPTER_TITLE = re.compile(rf"^{_CHAPTER_NO}(?:[：:].*)?$")
_HASH_TITLE = re.compile(rf"^#{{1,6}}\s+({_CHAPTER_NO}(?:[：:].*?)?)\s*$")
_BOLD_TITLE = re.compile(rf"^\*\*({_CHAPTER_NO}(?:[：:][^*]*?)?)\*\*\s*$")
# Opening/closing fence for a code block; the run length gates the close.
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_BOM = "﻿"


def _frontmatter_lines(content: str) -> int:
    """Number of leading lines the YAML fence occupies (0 when there is none).

    Metadata is not prose: it is skipped by the checks and left untouched by the
    fixes, while reported line numbers stay real file line numbers.
    """
    if not content.startswith("---\n"):
        return 0
    end = content.find("\n---", 4)
    if end == -1:
        return 0
    return content[: end + 4].count("\n") + 1


def _fenced_line_numbers(lines: list[str]) -> set[int]:
    """1-based line numbers inside a fenced code block, markers included.

    The FORMAT.md rules describe prose. A fenced block is verbatim sample text —
    the convention docs quote badly-formatted headings on purpose — so linting
    inside one misreports, and rewriting inside one corrupts the example. An
    unterminated fence swallows the rest of the file, which is the safe
    direction: leave it alone rather than rewrite it.
    """
    inside: set[int] = set()
    open_char: str | None = None
    open_len = 0
    for idx, line in enumerate(lines, 1):
        match = _FENCE_RE.match(line)
        if open_char is None:
            if match:
                open_char = match.group(1)[0]
                open_len = len(match.group(1))
                inside.add(idx)
            continue
        inside.add(idx)
        if match and match.group(1)[0] == open_char and len(match.group(1)) >= open_len:
            open_char = None
    return inside


def _first_prose_line(lines: list[str], skip: int, fenced: set[int]) -> int | None:
    """0-based index of the first non-blank line outside frontmatter and fences."""
    for i, line in enumerate(lines):
        if i < skip or (i + 1) in fenced or not line.strip():
            continue
        return i
    return None


_TITLE_FIXES = (("chapter_title_has_hash", _HASH_TITLE), ("chapter_title_bold", _BOLD_TITLE))


def _title_issue(lines: list[str], skip: int, fenced: set[int]) -> dict | None:
    """The chapter-title rule for the first prose line, or None when it is a
    plain `第N章：標題`. Decorated titles are fixable; anything else is
    `chapter_title_missing`, which only the author can resolve."""
    i = _first_prose_line(lines, skip, fenced)
    if i is None or _CHAPTER_TITLE.match(lines[i]):
        return None
    rule = next((r for r, pattern in _TITLE_FIXES if pattern.match(lines[i])), "chapter_title_missing")
    return {"rule": rule, "line": i + 1, "text": lines[i].strip()[:80]}


def _fix_title(content: str, skip: int) -> tuple[str, str | None]:
    """Strip the heading marker or bold from the first prose line only."""
    lines = content.split("\n")
    i = _first_prose_line(lines, skip, _fenced_line_numbers(lines))
    if i is None:
        return content, None
    for rule, pattern in _TITLE_FIXES:
        m = pattern.match(lines[i])
        if m:
            lines[i] = m.group(1)
            return "\n".join(lines), rule
    return content, None


def check_text(content: str, *, category: str = "main") -> list[dict]:
    """FORMAT.md violations in one file, as {rule, line, text} (1-based lines).

    An empty file yields nothing — the corpus uses empty files as chapter
    placeholders.
    """
    if not content.strip(_BOM + " \t\r\n"):
        return []
    issues: list[dict] = []
    if content.startswith(_BOM):
        issues.append({"rule": "bom", "line": 1, "text": ""})
        content = content[1:]
    skip = _frontmatter_lines(content)
    lines = content.splitlines()
    fenced = _fenced_line_numbers(lines)
    for idx, line in enumerate(lines, 1):
        if idx <= skip or idx in fenced:
            continue
        for rule, pattern, anchored in _LINE_RULES:
            if pattern.match(line) if anchored else pattern.search(line):
                issues.append({"rule": rule, "line": idx, "text": line.strip()})
        for pattern in _META_COLON_OUTSIDE:
            if pattern.search(line):
                issues.append({"rule": "metadata_colon_outside_bold", "line": idx, "text": line.strip()})
                break
        if _INNER_VIEW.match(line):
            issues.append({"rule": "inner_view_inside_blockquote", "line": idx, "text": line.strip()})

    # Only main text carries a chapter title and the （第N章 完） marker; drafts
    # and reference files would report them as missing forever.
    if category == "main":
        title = _title_issue(lines, skip, fenced)
        if title:
            issues.append(title)
        stripped = content.rstrip()
        if stripped and not _CHAPTER_END.search(stripped):
            issues.append({"rule": "missing_chapter_end_marker", "line": len(lines), "text": lines[-1].strip()[:80]})
    issues.sort(key=lambda i: (i["line"], i["rule"]))
    return issues


def _fix_body(body: str) -> tuple[str, list[str]]:
    """Rewrite prose only — fenced code blocks pass through byte for byte."""
    lines = body.split("\n")
    fenced = _fenced_line_numbers(lines)
    if not fenced:
        return _fix_prose(body)

    out: list[str] = []
    changes: list[str] = []
    prose: list[str] = []

    def _flush_prose() -> None:
        if not prose:
            return
        fixed, fixed_rules = _fix_prose("\n".join(prose))
        out.append(fixed)
        changes.extend(fixed_rules)
        prose.clear()

    for idx, line in enumerate(lines, 1):
        if idx in fenced:
            _flush_prose()
            out.append(line)
        else:
            prose.append(line)
    _flush_prose()

    seen: list[str] = []
    for rule in changes:
        if rule not in seen:
            seen.append(rule)
    return "\n".join(out), seen


def _fix_prose(body: str) -> tuple[str, list[str]]:
    changes: list[str] = []

    def sub(rule: str, pattern: str, repl: str, text: str, flags: int = re.MULTILINE) -> str:
        new = re.sub(pattern, repl, text, flags=flags)
        if new != text:
            changes.append(rule)
        return new

    text = body
    # 幕標題混入章編號 → ### 第N幕：…
    text = sub(
        "act_title_has_chapter_number",
        rf"^(?:###\s+)?{_CHAPTER_NO}\s+({_ACT_NAME}[：:].+)$",
        r"### \1",
        text,
    )
    # #### 第N幕 → ### 第N幕
    text = sub("act_title_wrong_level", rf"^####(\s+{_ACT_NAME}[：:])", r"###\1", text)
    # **第N幕：標題** → ### 第N幕：標題
    text = sub(
        "act_title_bold_instead_of_heading",
        rf"^\*\*({_ACT_NAME}[：:].+?)\*\*[ \t]*$",
        r"### \1",
        text,
    )
    # **【第N幕：標題】** → ### 第N幕：標題
    text = sub("act_title_bracket_bold", rf"^\*\*【({_ACT_NAME})[：:](.+?)】\*\*[ \t]*$", r"### \1：\2", text)
    # ### **第N幕：標題** → ### 第N幕：標題
    text = sub("act_title_redundant_bold", rf"^###\s+\*\*({_ACT_NAME}[：:].+?)\*\*[ \t]*$", r"### \1", text)
    # `[ \t]*$`, not `\s*$`: under MULTILINE `\s*` also swallows the newline
    # and the blank line after the heading.
    for field in _META_FIELDS:
        text = sub("metadata_colon_outside_bold", rf"\*\*{field}\*\*[：:]\s*", rf"**{field}：** ", text, flags=0)
    text = sub("dialogue_colon_outside_bold", r"\*\*([^*【\n]+?)\*\*[：:]「", r"**\1：**「", text, flags=0)

    lines = text.split("\n")
    out: list[str] = []
    moved = False
    for i, line in enumerate(lines):
        m = re.match(r"^>\s*(\*\*【裏側視角.*?】\*\*)\s*$", line)
        if not m:
            out.append(line)
            continue
        out.append(m.group(1))
        # Keep the quote that follows separated from the heading now above it.
        if i + 1 < len(lines) and lines[i + 1].startswith(">") and lines[i + 1].strip() != ">":
            out.append("")
        moved = True
    if moved:
        changes.append("inner_view_inside_blockquote")
        text = "\n".join(out)

    # Mixed brackets （…) → （…）, then （…) markers written half-width.
    text = sub("mixed_paren", r"（([^）\n]+?)\)", r"（\1）", text, flags=0)
    text = sub(
        "halfwidth_paren_marker",
        r"\(第([一二三四五六七八九十百\d]+(?:章|幕|部)[^)]*?)\)",
        r"（第\1）",
        text,
        flags=0,
    )
    # Same rule can fire from several patterns (per metadata field); report once.
    seen: list[str] = []
    for c in changes:
        if c not in seen:
            seen.append(c)
    return text, seen


def fix_text(content: str) -> tuple[str, list[str]]:
    """Auto-fixable violations rewritten. Returns (new_content, rule ids fixed).

    Rewrites never touch the YAML frontmatter. `missing_chapter_end_marker` and
    `chapter_title_missing` are deliberately not auto-fixable: only the author
    knows the title and where a chapter ends.
    """
    if not content.strip(_BOM + " \t\r\n"):
        return content, []
    leading: list[str] = []
    if content.startswith(_BOM):
        content = content[1:]
        leading.append("bom")
    skip = _frontmatter_lines(content)
    content, title_rule = _fix_title(content, skip)
    if title_rule:
        leading.append(title_rule)
    if skip:
        lines = content.split("\n")
        head = "\n".join(lines[:skip])
        body = "\n".join(lines[skip:])
        fixed, changes = _fix_body(body)
        new = f"{head}\n{fixed}" if changes else content
    else:
        new, changes = _fix_body(content)
    changes = leading + changes
    return (new if changes else content), changes
