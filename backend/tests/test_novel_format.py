"""FORMAT.md lint/fix rules (port of the desktop check_format/fix_format)."""

import pytest

from services.novel_format import check_text, fix_text, variant_for

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
        ("## 第3章：標題", "chapter_title_has_hash"),
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


def test_nordkale_rule_only_fires_for_that_variant():
    content = "第1章：開場\n\n> **【裏側視角】**\n> 內心。\n\n（第1章 完）\n"
    assert "inner_view_inside_blockquote" not in _rules(content)
    assert "inner_view_inside_blockquote" in _rules(content, variant="nordkale")


def test_variant_is_derived_from_the_work_folder():
    assert variant_for("挪德卡萊 - 最後的月之容器/第01章.md") == "nordkale"
    assert variant_for("流螢 - 熔火之繭/第01章.md") == "default"


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


def test_fix_moves_the_nordkale_heading_out_of_the_blockquote():
    content = "第1章\n\n> **【裏側視角】**\n> 內心。\n\n（第1章 完）\n"
    fixed, changes = fix_text(content, variant="nordkale")
    assert "inner_view_inside_blockquote" in changes
    assert "**【裏側視角】**\n\n> 內心。" in fixed
    # Without the variant the line is left alone.
    assert fix_text(content)[1] == []


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
