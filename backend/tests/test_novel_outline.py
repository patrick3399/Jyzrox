"""Plot outline convention + parsing."""

from services.novel_outline import find_outline, link_chapters, outline_path, parse_outline

# The outline shape: one ### node per chapter, bolded-bullet beats, detail lines.
_HEADING_OUTLINE = """---
title: 大綱
---

# 全書大綱

## 逐章大綱

### 第7章·星辰之門
**項目狀態：** 脫離掌控

*   **第一幕：劫獄**
    *   **劇情節點：** 甲攔截運輸艦。
*   **第二幕：代碼**

### 第8章·夢境
**項目狀態：** 連線

*   **第一幕：黃金時刻**

### 番外：無章節對應
只是一個構想。
"""


def test_canonical_outline_path_is_the_setting_folder_outline():
    """The author keeps the outline in Setting/ next to the setting notes;
    Setting/ classifies it as reference by its filename."""
    assert outline_path("作品A") == "作品A/Setting/大綱.md"


def test_parses_headings_into_nodes_with_beats_and_chapter_numbers():
    nodes = parse_outline(_HEADING_OUTLINE)
    # `# 全書大綱` is level 1, which is not a node.
    assert [n["title"] for n in nodes] == ["逐章大綱", "第7章·星辰之門", "第8章·夢境", "番外：無章節對應"]
    chapter_nodes = [n for n in nodes if n["chapter_no"] is not None]
    assert [n["chapter_no"] for n in chapter_nodes] == [7, 8]
    assert chapter_nodes[0]["preview"].startswith("項目狀態")
    assert [b["title"] for b in chapter_nodes[0]["beats"]] == ["第一幕：劫獄", "第二幕：代碼"]


def test_node_line_numbers_are_real_file_lines_past_the_frontmatter():
    lines = _HEADING_OUTLINE.splitlines()
    for n in parse_outline(_HEADING_OUTLINE):
        assert lines[n["line"] - 1].endswith(n["title"])


def test_bold_chapter_lines_are_not_nodes():
    """Only headings are nodes; a `**第N章·…**：` line must be converted to a
    heading in the corpus (plan Task B3), not guessed at by the parser."""
    assert parse_outline("## 逐章大綱\n\n**第1章·開場**：概要\n") == [
        {
            "order": 0,
            "level": 2,
            "title": "逐章大綱",
            "line": 1,
            "chapter_no": None,
            "preview": "第1章·開場：概要",
            "beats": [],
        }
    ]


def test_empty_outline_yields_no_nodes():
    assert parse_outline("") == []
    assert parse_outline("# 大綱\n\n還沒開始寫。\n") == []


def test_link_chapters_matches_by_number_not_by_title():
    nodes = [n for n in parse_outline(_HEADING_OUTLINE) if n["level"] == 3]
    linked = link_chapters(nodes, [{"path": "作品A/07.md"}, {"path": "作品A/09.md"}])
    assert linked[0]["chapter_path"] == "作品A/07.md"
    assert linked[1]["chapter_path"] is None
    assert linked[2]["chapter_path"] is None


def test_link_chapters_prefers_the_base_chapter_over_its_parts():
    nodes = [{"chapter_no": 1}]
    chapters = [{"path": "作品A/01.md"}, {"path": "作品A/01-1.md"}]
    assert link_chapters(nodes, chapters)[0]["chapter_path"] == "作品A/01.md"


def test_find_outline_only_accepts_the_setting_outline(tmp_path):
    (tmp_path / "作品A" / "參考").mkdir(parents=True)
    (tmp_path / "作品A" / "參考" / "大綱.md").write_text("# x\n", encoding="utf-8")
    assert find_outline(tmp_path, "作品A") is None
    (tmp_path / "作品A" / "Setting").mkdir()
    (tmp_path / "作品A" / "Setting" / "大綱.md").write_text("# x\n", encoding="utf-8")
    assert find_outline(tmp_path, "作品A") == "作品A/Setting/大綱.md"


def test_find_outline_rejects_a_traversing_work(tmp_path):
    assert find_outline(tmp_path, "../../etc") is None
