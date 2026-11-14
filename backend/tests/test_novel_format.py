"""FORMAT.md lint/fix rules (port of the desktop check_format/fix_format)."""

import pytest

from services.novel_format import check_text, fix_text

_GOOD = (
    "第1章：開場\n\n### 第一幕：抵達\n\n**地點：** 城門\n**時間：** 黃昏\n\n**張三：**「我來了。」\n\n（第1章 完）\n"
)


def _rules(content, **kw):
    return [i["rule"] for i in check_text(content, **kw)]


def test_clean_chapter_has_no_issues():
    assert check_text(_GOOD) == []


def test_empty_file_is_a_placeholder_not_a_violation():
    """The corpus uses empty files to reserve chapter numbers."""
    assert check_text("") == []
    assert check_text("\n\n") == []


@pytest.mark.parametrize(
    ("line", "rule"),
    [
        ("### 第3章 第一幕：抵達", "act_title_has_chapter_number"),
        ("#### 第一幕：抵達", "act_title_wrong_level"),
        ("**第一幕：抵達**", "act_title_bold_instead_of_heading"),
        ("### **第一幕：抵達**", "act_title_redundant_bold"),
        ("**地點**：城門", "metadata_colon_outside_bold"),
        ("**張三**：「我來了。」", "dialogue_colon_outside_bold"),
        ("(第1章 完)", "halfwidth_paren_marker"),
    ],
)
def test_each_rule_reports_its_line(line, rule):
    content = f"第1章：開場\n\n{line}\n\n（第1章 完）\n"
    issues = check_text(content)
    assert rule in [i["rule"] for i in issues]
    hit = next(i for i in issues if i["rule"] == rule)
    assert hit["line"] == 3
    assert hit["text"] == line


def test_missing_chapter_end_marker_reported_for_main_text_only():
    no_marker = "第1章：開場\n\n正文。\n"
    assert "missing_chapter_end_marker" in _rules(no_marker)
    # A draft/reference file never carries the marker — reporting it would be
    # permanent noise.
    assert "missing_chapter_end_marker" not in _rules(no_marker, category="draft")


def test_frontmatter_is_not_linted_and_line_numbers_stay_real():
    """A summary line must not be mistaken for prose, and every reported line
    number must still point at the real line of the file."""
    content = "---\nsummary: 他說：「好」\n---\n\n第1章：開場\n\n**地點**：城門\n\n（第1章 完）\n"
    issues = check_text(content)
    assert [i["rule"] for i in issues] == ["metadata_colon_outside_bold"]
    assert issues[0]["line"] == 7


def test_metadata_rule_reported_once_per_line():
    content = "第1章\n\n**地點**：城門　**時間**：黃昏\n\n（第1章 完）\n"
    assert _rules(content).count("metadata_colon_outside_bold") == 1


# ── fixes ──────────────────────────────────────────────────────────────────


def test_fix_rewrites_act_titles_metadata_and_dialogue():
    broken = (
        "第1章：開場\n\n"
        "第1章 第一幕：抵達\n\n"
        "#### 第二幕：對峙\n\n"
        "**第三幕：離別**\n\n"
        "### **終幕：夜**\n\n"
        "**地點**：城門\n\n"
        "**張三**：「我來了。」\n\n"
        "(第1章 完)\n"
    )
    fixed, changes = fix_text(broken)
    assert "### 第一幕：抵達" in fixed
    assert "### 第二幕：對峙" in fixed
    assert "### 第三幕：離別" in fixed
    assert "### 終幕：夜" in fixed
    assert "**地點：** 城門" in fixed
    assert "**張三：**「我來了。」" in fixed
    assert "（第1章 完）" in fixed
    assert set(changes) >= {
        "act_title_has_chapter_number",
        "act_title_wrong_level",
        "act_title_bold_instead_of_heading",
        "act_title_redundant_bold",
        "metadata_colon_outside_bold",
        "dialogue_colon_outside_bold",
        "halfwidth_paren_marker",
    }
    # Fixing must actually satisfy the checker.
    assert check_text(fixed) == []


def test_fix_is_idempotent_and_reports_nothing_on_clean_text():
    fixed, changes = fix_text(_GOOD)
    assert changes == []
    assert fixed == _GOOD


def test_fix_reports_each_rule_once_even_across_several_fields():
    broken = "第1章\n\n**地點**：城門\n**時間**：黃昏\n**人物**：張三\n\n（第1章 完）\n"
    _, changes = fix_text(broken)
    assert changes.count("metadata_colon_outside_bold") == 1


def test_fix_leaves_frontmatter_untouched():
    content = "---\nsummary: 他說：「好」\n---\n\n第1章\n\n**地點**：城門\n\n（第1章 完）\n"
    fixed, changes = fix_text(content)
    assert fixed.startswith("---\nsummary: 他說：「好」\n---\n")
    assert "**地點：** 城門" in fixed
    assert changes == ["metadata_colon_outside_bold"]


def test_fix_moves_the_inner_view_heading_out_of_the_blockquote_in_any_work():
    """The rule used to run only for one work (matched by folder name); two
    other works use the same heading."""
    content = "第1章：開場\n\n> **【裏側視角】**\n> 內心。\n\n（第1章 完）\n"
    assert "inner_view_inside_blockquote" in _rules(content)
    fixed, changes = fix_text(content)
    assert "inner_view_inside_blockquote" in changes
    assert "**【裏側視角】**\n\n> 內心。" in fixed


def test_fix_never_invents_a_chapter_end_marker():
    """Only the author knows where a chapter ends — the marker is lint-only."""
    content = "第1章：開場\n\n正文。\n"
    fixed, changes = fix_text(content)
    assert fixed == content
    assert changes == []
    assert "missing_chapter_end_marker" in _rules(content)


# ---------------------------------------------------------------------------
# Fenced code blocks
# ---------------------------------------------------------------------------


_FENCED = """第1章：開場

正文開頭。

```markdown
#### 第一幕：範例
**地點**: 這是文件裡故意寫錯的範例
```

正文結尾。（第1章 完）
"""


def test_fix_text_leaves_fenced_examples_untouched():
    """FORMAT.md quotes badly-formatted headings on purpose as examples.

    Rewriting them would corrupt the very documentation that explains the rule.
    """
    fixed, changes = fix_text(_FENCED)
    assert "#### 第一幕：範例" in fixed
    assert "**地點**: 這是文件裡故意寫錯的範例" in fixed
    assert changes == []
    assert fixed == _FENCED


def test_check_text_does_not_report_issues_inside_a_fence():
    issues = check_text(_FENCED)
    assert [i["rule"] for i in issues] == []


def test_prose_outside_a_fence_is_still_fixed():
    """The fence must not become a blanket exemption for the whole file."""
    content = "第1章：開場\n\n```\n#### 第一幕：範例\n```\n\n#### 第二幕：真正的內容\n\n（第1章 完）\n"
    fixed, changes = fix_text(content)
    assert "act_title_wrong_level" in changes
    # Inside the fence: untouched. Outside: corrected to ###.
    assert "```\n#### 第一幕：範例\n```" in fixed
    assert "### 第二幕：真正的內容" in fixed


def test_tilde_fences_are_honoured_too():
    content = "第1章：開場\n\n~~~\n#### 第一幕：範例\n~~~\n\n（第1章 完）\n"
    fixed, changes = fix_text(content)
    assert changes == []
    assert "#### 第一幕：範例" in fixed


def test_unterminated_fence_is_left_alone_to_the_end_of_file():
    """Safer to skip than to rewrite text whose structure we misread."""
    content = "第1章：開場\n\n```\n#### 第一幕：範例\n**地點**: x\n"
    fixed, changes = fix_text(content)
    assert changes == []
    assert fixed == content


def test_a_longer_closing_run_still_closes_the_fence():
    content = "第1章：開場\n\n```\n#### 範例\n````\n\n#### 第二幕：真的\n\n（第1章 完）\n"
    fixed, changes = fix_text(content)
    assert "act_title_wrong_level" in changes
    assert "### 第二幕：真的" in fixed
    assert "#### 範例" in fixed


# ── Corpus fit (2026-11-05) ────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("first", "rule", "fixed_first"),
    [
        ("### 第一章：開場", "chapter_title_has_hash", "第一章：開場"),
        ("# 第12章：開場", "chapter_title_has_hash", "第12章：開場"),
        ("**第一章：開場**", "chapter_title_bold", "第一章：開場"),
    ],
)
def test_decorated_chapter_titles_are_reported_and_fixed(first, rule, fixed_first):
    """The old rule only knew Arabic numerals, so `### 第一章：…` and
    `**第一章：…**` passed the lint in 43 real chapters."""
    content = f"{first}\n\n正文。\n\n（第1章 完）\n"
    assert _rules(content) == [rule]
    fixed, changes = fix_text(content)
    assert changes == [rule]
    assert fixed.splitlines()[0] == fixed_first
    assert check_text(fixed) == []


@pytest.mark.parametrize("first", ["### 【序】", "**第一部分**", "她推開門。"])
def test_main_chapter_without_a_chapter_title_is_reported(first):
    content = f"{first}\n\n正文。\n\n（第1章 完）\n"
    assert _rules(content) == ["chapter_title_missing"]
    assert fix_text(content)[1] == []  # only the author can write the title


def test_chapter_title_rule_applies_to_main_text_only():
    content = "她推開門。\n"
    assert "chapter_title_missing" not in _rules(content, category="draft")


def test_bare_chapter_title_without_a_subtitle_is_accepted():
    assert "chapter_title_missing" not in _rules("第1章\n\n正文。\n\n（第1章 完）\n")


def test_chapter_title_is_found_after_frontmatter_and_blank_lines():
    content = "---\nsummary: s\n---\n\n\n第1章：開場\n\n（第1章 完）\n"
    assert check_text(content) == []


def test_chapter_headings_inside_a_chapter_are_left_alone():
    """One real chapter is divided into `### 第一章：…` sections; rewriting
    every such heading would flatten that structure. Only the first prose line
    is the chapter title."""
    content = "第1章：開場\n\n### 第一章：上\n\n正文。\n\n### 第二章：下\n\n（第1章 完）\n"
    assert check_text(content) == []
    assert fix_text(content) == (content, [])


def test_act_title_with_a_chinese_numeral_chapter_number_is_fixed():
    """`### 第六章 第二幕：…` slipped through: the rule only knew `第6章`."""
    content = "第6章：開場\n\n### 第六章 第二幕：抵達\n\n（第6章 完）\n"
    assert _rules(content) == ["act_title_has_chapter_number"]
    fixed, changes = fix_text(content)
    assert changes == ["act_title_has_chapter_number"]
    assert "### 第二幕：抵達" in fixed


def test_act_end_marker_naming_the_chapter_is_not_an_act_title():
    """Real chapters close each act with `（第六章 第四幕 完）`; matching the
    chapter-plus-act shape anywhere in a line reported every one of them."""
    content = "第6章：開場\n\n### 第一幕：抵達\n\n正文。\n\n（第六章 第一幕 完）\n\n（第6章 完）\n"
    assert check_text(content) == []


def test_bracketed_bold_act_title_becomes_a_heading():
    """80 act titles in one real work were `**【第一幕：…】**`, so the reader
    found no acts and the lint reported nothing."""
    content = "第1章：開場\n\n**【第一幕：抵達】**\n\n**【終幕:夜】**\n\n（第1章 完）\n"
    assert _rules(content).count("act_title_bracket_bold") == 2
    fixed, changes = fix_text(content)
    assert changes == ["act_title_bracket_bold"]
    assert "### 第一幕：抵達" in fixed and "### 終幕：夜" in fixed
    assert check_text(fixed) == []


def test_fixing_an_act_title_keeps_the_blank_line_after_it():
    """The act-title fixes ended in `\\s*$`, which under MULTILINE also ate
    the following blank line — one real chapter lost three lines."""
    content = "第1章：開場\n\n**第一幕：抵達**\n\n正文。\n\n**【第二幕：夜】**\n\n正文。\n\n（第1章 完）\n"
    fixed, _ = fix_text(content)
    assert fixed == "第1章：開場\n\n### 第一幕：抵達\n\n正文。\n\n### 第二幕：夜\n\n正文。\n\n（第1章 完）\n"


def test_bom_is_reported_and_removed():
    """A BOM hid the first line from every anchored rule and made a summary
    insert leave the BOM in the middle of the file."""
    content = "﻿第1章：開場\n\n（第1章 完）\n"
    assert _rules(content) == ["bom"]
    fixed, changes = fix_text(content)
    assert changes == ["bom"]
    assert fixed == content[1:]
