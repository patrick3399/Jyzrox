"""FORMAT.md conformance: lint + auto-fix for novel markdown.

Port of the desktop tools (`check_format.py` / `fix_format.py` in the content
repo) so the same rules run server-side, behind the API, and can later gate a
publish step. Pure text in / findings out — no git, no DB, no filesystem.

Rules are identified by stable snake_case ids; the UI owns their wording (i18n).
The rule set and the fix rewrites are kept deliberately identical to the desktop
scripts: the same chapter must not lint differently depending on where it was
checked.

`variant` carries per-work extra rules, mirroring how the desktop scripts
auto-enable their Nordkale rule from the folder name.
"""

from __future__ import annotations

import re

_ACT_NAME = r"(?:第[一二三四五六七八九十百]+幕|序幕|終幕)"

# Line-level checks: (rule id, compiled pattern, match-not-search).
_LINE_RULES: list[tuple[str, re.Pattern[str], bool]] = [
    # 章標題誤加 #（章標題直接寫文字）
    ("chapter_title_has_hash", re.compile(r"^#{1,6}\s+第\d+章"), True),
    # 幕標題混入章編號：第N章 第N幕
    ("act_title_has_chapter_number", re.compile(rf"第\d+章\s+{_ACT_NAME}"), False),
    # 幕標題層級錯誤：#### 第N幕
    ("act_title_wrong_level", re.compile(rf"^####\s+{_ACT_NAME}[：:]"), True),
    # 幕標題用粗體替代標題
    ("act_title_bold_instead_of_heading", re.compile(rf"^\*\*{_ACT_NAME}[：:]"), True),
    # ### **第N幕** 多餘粗體
    ("act_title_redundant_bold", re.compile(rf"^###\s+\*\*{_ACT_NAME}"), True),
    # 對話冒號在粗體外：**角色名**：「
    ("dialogue_colon_outside_bold", re.compile(r"\*\*[^*【]+\*\*\s*[：:]「"), False),
    # 結尾標記用半形括號
    ("halfwidth_paren_marker", re.compile(r"\(第[一二三四五六七八九十百\d]+(?:章|幕|部)"), False),
]

_META_FIELDS = ("地點", "時間", "人物", "主要人物", "狀態")
_META_COLON_OUTSIDE = [re.compile(rf"\*\*{f}\*\*\s*[：:]") for f in _META_FIELDS]

# Nordkale's 裏側視角 heading must sit outside the blockquote it introduces.
_NORDKALE_INNER_VIEW = re.compile(r"^>\s*\*\*【裏側視角")
_CHAPTER_END = re.compile(r"（.{1,20}完）\s*$")


def variant_for(rel_path: str) -> str:
    """Per-work rule variant, derived from the work folder like the desktop
    scripts do (they switch on the folder name too)."""
    work = rel_path.split("/", 1)[0]
    return "nordkale" if work.startswith("挪德卡萊") else "default"


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


def check_text(content: str, *, variant: str = "default", category: str = "main") -> list[dict]:
    """FORMAT.md violations in one file, as {rule, line, text} (1-based lines).

    An empty file yields nothing — the corpus uses empty files as chapter
    placeholders.
    """
    if not content.strip():
        return []
    issues: list[dict] = []
    skip = _frontmatter_lines(content)
    lines = content.splitlines()
    for idx, line in enumerate(lines, 1):
        if idx <= skip:
            continue
        for rule, pattern, anchored in _LINE_RULES:
            if pattern.match(line) if anchored else pattern.search(line):
                issues.append({"rule": rule, "line": idx, "text": line.strip()})
        for pattern in _META_COLON_OUTSIDE:
            if pattern.search(line):
                issues.append({"rule": "metadata_colon_outside_bold", "line": idx, "text": line.strip()})
                break
        if variant == "nordkale" and _NORDKALE_INNER_VIEW.match(line):
            issues.append({"rule": "inner_view_inside_blockquote", "line": idx, "text": line.strip()})

    # Only main text carries the （第N章 完） marker; drafts and reference files
    # would report it as missing forever.
    if category == "main":
        stripped = content.rstrip()
        if stripped and not _CHAPTER_END.search(stripped):
            issues.append({"rule": "missing_chapter_end_marker", "line": len(lines), "text": lines[-1].strip()[:80]})
    issues.sort(key=lambda i: (i["line"], i["rule"]))
    return issues


def _fix_body(body: str, variant: str) -> tuple[str, list[str]]:
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
        rf"^(?:###\s+)?第\d+章\s+({_ACT_NAME}[：:].+)$",
        r"### \1",
        text,
    )
    # #### 第N幕 → ### 第N幕
    text = sub("act_title_wrong_level", rf"^####(\s+{_ACT_NAME}[：:])", r"###\1", text)
    # **第N幕：標題** → ### 第N幕：標題
    text = sub(
        "act_title_bold_instead_of_heading",
        rf"^\*\*({_ACT_NAME}[：:].+?)\*\*\s*$",
        r"### \1",
        text,
    )
    # ### **第N幕：標題** → ### 第N幕：標題
    text = sub("act_title_redundant_bold", rf"^###\s+\*\*({_ACT_NAME}[：:].+?)\*\*\s*$", r"### \1", text)
    for field in _META_FIELDS:
        text = sub("metadata_colon_outside_bold", rf"\*\*{field}\*\*[：:]\s*", rf"**{field}：** ", text, flags=0)
    text = sub("dialogue_colon_outside_bold", r"\*\*([^*【\n]+?)\*\*[：:]「", r"**\1：**「", text, flags=0)

    if variant == "nordkale":
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


def fix_text(content: str, *, variant: str = "default") -> tuple[str, list[str]]:
    """Auto-fixable violations rewritten. Returns (new_content, rule ids fixed).

    Rewrites never touch the YAML frontmatter, and `missing_chapter_end_marker`
    is deliberately not auto-fixable: only the author knows where a chapter ends.
    """
    if not content.strip():
        return content, []
    skip = _frontmatter_lines(content)
    if skip:
        lines = content.split("\n")
        head = "\n".join(lines[:skip])
        body = "\n".join(lines[skip:])
        fixed, changes = _fix_body(body, variant)
        return (f"{head}\n{fixed}" if changes else content), changes
    fixed, changes = _fix_body(content, variant)
    return (fixed if changes else content), changes
