"""Plot outline convention + parsing (Phase 1.7)."""

from services.novel_outline import find_outline, link_chapters, outline_path, parse_outline

# The shape the corpus uses: ### chapter node, bolded-bullet beats, detail lines.
_HEADING_OUTLINE = """---
title: 大綱
---

# 全書大綱

前言，不屬於任何節點。

### 第7章：星核的救贖
**項目狀態：** 脫離公司掌控

*   **第一幕：命運的劫獄**
    *   **劇情節點：** 卡芙卡攔截運輸艦。
*   **第二幕：銀狼的代碼**

### 第8章：匹諾康尼的幻夢
**項目狀態：** 夢境投影連線

*   **第一幕：黃金的時刻**

### 番外：無章節對應
只是一個構想。
"""

_BULLET_OUTLINE = """# 關鍵劇情節點

*   **第1章（受肉儀式）：** 流螢被裝入裝甲。
*   **第2章（馴火）：** 投入戰場。
*   **不是章節的粗體項目：** 應被忽略。
"""


def test_canonical_outline_path_is_under_the_reference_folder():
    """A work-root 大綱.md would classify as main text and pollute the chapter
    list, so the convention puts it under 參考/."""
    assert outline_path("作品A") == "作品A/參考/大綱.md"


def test_parses_headings_into_nodes_with_beats_and_chapter_numbers():
    nodes = parse_outline(_HEADING_OUTLINE)
    assert [n["title"] for n in nodes] == ["第7章：星核的救贖", "第8章：匹諾康尼的幻夢", "番外：無章節對應"]
    assert [n["chapter_no"] for n in nodes] == [7, 8, None]
    assert [n["order"] for n in nodes] == [0, 1, 2]
    assert nodes[0]["preview"].startswith("項目狀態")
    # Beats are the labelled sub-sections; `**劇情節點：** …` is a detail line.
    assert [b["title"] for b in nodes[0]["beats"]] == ["第一幕：命運的劫獄", "第二幕：銀狼的代碼"]


def test_node_line_numbers_are_real_file_lines_past_the_frontmatter():
    nodes = parse_outline(_HEADING_OUTLINE)
    lines = _HEADING_OUTLINE.splitlines()
    for n in nodes:
        assert lines[n["line"] - 1].endswith(n["title"])


def test_preamble_before_the_first_node_is_ignored():
    nodes = parse_outline(_HEADING_OUTLINE)
    assert all("前言" not in n["preview"] for n in nodes)


def test_heading_less_outline_falls_back_to_chapter_bullets():
    """The outline already written in the corpus lists chapters as bolded bullets
    with the synopsis inline."""
    nodes = parse_outline(_BULLET_OUTLINE)
    assert [n["chapter_no"] for n in nodes] == [1, 2]
    assert nodes[0]["title"] == "第1章（受肉儀式）"
    assert nodes[0]["preview"] == "流螢被裝入裝甲。"


def test_empty_outline_yields_no_nodes():
    assert parse_outline("") == []
    assert parse_outline("# 大綱\n\n還沒開始寫。\n") == []


def test_link_chapters_matches_by_number_not_by_title():
    """Chapters are named 01.md/02.md, so a node keeps its link across renames."""
    nodes = parse_outline(_HEADING_OUTLINE)
    chapters = [{"path": "作品A/07.md"}, {"path": "作品A/09.md"}]
    linked = link_chapters(nodes, chapters)
    assert linked[0]["chapter_path"] == "作品A/07.md"
    # Chapter 8 is planned but not written yet, and a node with no chapter number
    # can never be linked.
    assert linked[1]["chapter_path"] is None
    assert linked[2]["chapter_path"] is None


def test_find_outline_accepts_the_alternate_names(tmp_path):
    (tmp_path / "作品A" / "參考").mkdir(parents=True)
    assert find_outline(tmp_path, "作品A") is None
    (tmp_path / "作品A" / "參考" / "outline.md").write_text("# x\n", encoding="utf-8")
    assert find_outline(tmp_path, "作品A") == "作品A/參考/outline.md"
    # The canonical name wins when both exist.
    (tmp_path / "作品A" / "參考" / "大綱.md").write_text("# x\n", encoding="utf-8")
    assert find_outline(tmp_path, "作品A") == "作品A/參考/大綱.md"


def test_find_outline_rejects_a_traversing_work(tmp_path):
    assert find_outline(tmp_path, "../../etc") is None
