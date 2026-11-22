"""Unit tests for services.gallery_sort (compiled against the PostgreSQL dialect)."""

from datetime import datetime

import pytest
from sqlalchemy import Column, Integer, MetaData, Table, select
from sqlalchemy.dialects import postgresql

from services.gallery_sort import (
    SORT_SPECS,
    encode_value,
    keyset_after,
    order_by,
    parse_cursor_value,
    resolve_direction,
)

_t = Table("g", MetaData(), Column("id", Integer), Column("v", Integer))


def _order_sql(key: str, direction: str) -> str:
    stmt = select(_t.c.id).order_by(*order_by(SORT_SPECS[key], _t.c.v, _t.c.id, direction))
    sql = str(stmt.compile(dialect=postgresql.dialect()))
    return sql[sql.index("ORDER BY") + len("ORDER BY ") :]


def _where_sql(key: str, direction: str, value) -> str:
    cond = keyset_after(SORT_SPECS[key], _t.c.v, _t.c.id, direction, value, 7)
    return str(cond.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def test_order_by_natural_policy_emits_postgres_default_nulls_clauses():
    for key in ("added_at", "content_updated_at"):
        assert _order_sql(key, "desc") == "g.v DESC NULLS FIRST, g.id DESC"
        assert _order_sql(key, "asc") == "g.v ASC NULLS LAST, g.id ASC"
        assert "DESC NULLS LAST" not in _order_sql(key, "desc")


def test_order_by_last_policy_puts_nulls_last_in_both_directions():
    for key in ("posted_at", "rating", "pages", "title"):
        assert _order_sql(key, "desc") == "g.v DESC NULLS LAST, g.id DESC"
        assert _order_sql(key, "asc") == "g.v ASC NULLS LAST, g.id ASC"


def test_resolve_direction_invalid_or_missing_falls_back_to_default():
    assert resolve_direction(SORT_SPECS["title"], None) == "asc"
    assert resolve_direction(SORT_SPECS["title"], "sideways") == "asc"
    assert resolve_direction(SORT_SPECS["pages"], "") == "desc"
    assert resolve_direction(SORT_SPECS["title"], "desc") == "desc"
    assert resolve_direction(SORT_SPECS["pages"], "asc") == "asc"


def test_parse_cursor_value_by_kind():
    assert parse_cursor_value(SORT_SPECS["rating"], "") is None
    assert parse_cursor_value(SORT_SPECS["rating"], "4") == 4
    assert parse_cursor_value(SORT_SPECS["posted_at"], "2024-05-05T00:00:00") == datetime(2024, 5, 5)
    assert parse_cursor_value(SORT_SPECS["title"], "abc") == "abc"
    with pytest.raises(ValueError):
        parse_cursor_value(SORT_SPECS["pages"], "x")
    with pytest.raises(ValueError):
        parse_cursor_value(SORT_SPECS["added_at"], "nope")


def test_encode_value():
    assert encode_value(None) is None
    assert encode_value(3) == "3"
    assert encode_value(datetime(2024, 1, 2, 3, 4, 5)) == "2024-01-02T03:04:05"


def test_keyset_last_policy_value_includes_null_tail_both_directions():
    for direction, op in (("desc", "<"), ("asc", ">")):
        sql = _where_sql("rating", direction, 3)
        assert f"g.v {op} 3" in sql
        assert f"g.id {op} 7" in sql
        assert "g.v IS NULL" in sql


def test_keyset_last_policy_null_cursor_stays_inside_null_tail():
    assert _where_sql("rating", "desc", None) == "g.v IS NULL AND g.id < 7"
    assert _where_sql("rating", "asc", None) == "g.v IS NULL AND g.id > 7"


def test_keyset_natural_desc_value_excludes_null_rows():
    sql = _where_sql("added_at", "desc", 3)
    assert "IS NULL" not in sql
    assert "g.v < 3" in sql and "g.id < 7" in sql


def test_keyset_natural_desc_null_cursor_continues_into_non_null_rows():
    sql = _where_sql("added_at", "desc", None)
    assert "g.v IS NULL AND g.id < 7" in sql
    assert "g.v IS NOT NULL" in sql


def test_keyset_natural_asc_includes_null_tail():
    sql = _where_sql("added_at", "asc", 3)
    assert "g.v > 3" in sql and "g.id > 7" in sql and "g.v IS NULL" in sql
    assert _where_sql("added_at", "asc", None) == "g.v IS NULL AND g.id > 7"
