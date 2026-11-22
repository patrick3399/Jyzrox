"""Regression tests for the posted-date ("posted_at") sort.

``galleries.posted_at`` is nullable and most local/social-media galleries have
none. Two bugs made the Library posted-date sort unusable:

- PostgreSQL ``ORDER BY posted_at DESC`` puts NULLs first, so the undated
  galleries buried every dated one.
- A page ending on an undated gallery encoded an empty cursor value, and the
  next page failed with 400 "Invalid cursor value".

SQLite (the test DB) already sorts NULLs last on DESC, so the ordering contract
is asserted on the SQL that is actually emitted.
"""

from sqlalchemy import event, text
from sqlalchemy.dialects import postgresql


async def _g(db, sid: str, posted: str | None, source: str = "pat") -> int:
    # SQLite compares datetimes as strings: use the ORM's '.ffffff' shape so keyset
    # equality (tie-break) matches what the cursor binds.
    await db.execute(
        text(
            "INSERT INTO galleries (source, source_id, title, pages, download_status, tags_array, "
            "posted_at, visibility) "
            "VALUES (:s, :sid, :t, 1, 'completed', '[]', :p, 'public')"
        ),
        {"s": source, "sid": sid, "t": f"G{sid}", "p": f"{posted}.000000" if posted else None},
    )
    await db.commit()
    return (
        await db.execute(text("SELECT id FROM galleries WHERE source=:s AND source_id=:sid"), {"s": source, "sid": sid})
    ).scalar()


async def _walk(client, limit: int) -> list[int]:
    """Follow the Library flow: first page without cursor, then next_cursor."""
    seen: list[int] = []
    params = {"q": "source:pat sort:posted_at", "limit": limit}
    for _ in range(20):
        r = await client.get("/api/search/", params=params)
        assert r.status_code == 200, r.text
        data = r.json()
        seen.extend(i["id"] for i in data["items"])
        if not data["has_next"]:
            return seen
        params = {**params, "cursor": data["next_cursor"]}
    raise AssertionError("pagination did not terminate")


async def test_search_posted_at_cursor_past_undated_gallery_does_not_400(client, db_session):
    new = await _g(db_session, "new", "2024-09-01 00:00:00")
    tie_a = await _g(db_session, "tie_a", "2024-05-05 00:00:00")
    tie_b = await _g(db_session, "tie_b", "2024-05-05 00:00:00")
    null_a = await _g(db_session, "null_a", None)
    null_b = await _g(db_session, "null_b", None)
    null_c = await _g(db_session, "null_c", None)

    seen = await _walk(client, limit=1)

    # Dated newest-first (ties by id DESC), then undated by id DESC — no gaps, no dupes.
    assert seen == [new, tie_b, tie_a, null_c, null_b, null_a]


async def test_search_posted_at_page_size_spanning_dated_and_undated_rows(client, db_session):
    dated = [await _g(db_session, f"d{i}", f"2024-0{i + 1}-01 00:00:00") for i in range(3)]
    undated = [await _g(db_session, f"n{i}", None) for i in range(4)]

    seen = await _walk(client, limit=2)

    assert seen == list(reversed(dated)) + list(reversed(undated))


async def test_search_posted_at_sort_emits_nulls_last(client, db_session, db_engine):
    await _g(db_session, "x", "2024-01-01 00:00:00")
    await _g(db_session, "y", None)
    await _g(db_session, "z", None)

    statements: list[str] = []

    def _capture(conn, cursor, statement, params, context, executemany):
        if "ORDER BY" in statement and "galleries" in statement:
            statements.append(statement)

    event.listen(db_engine.sync_engine, "before_cursor_execute", _capture)
    try:
        r = await client.get("/api/search/", params={"q": "source:pat sort:posted_at", "limit": 1})
        assert r.status_code == 200
        r = await client.get(
            "/api/search/",
            params={"q": "source:pat sort:posted_at", "limit": 1, "cursor": r.json()["next_cursor"]},
        )
        assert r.status_code == 200
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", _capture)

    ordered = [s for s in statements if "posted_at DESC" in s]
    assert len(ordered) == 2, statements  # page-based first page + keyset page
    # Without NULLS LAST, PostgreSQL would list every undated gallery first.
    assert all("posted_at DESC NULLS LAST" in s for s in ordered), ordered


def _explorer_order_sql(direction: str) -> str:
    from services.explorer_query import ExplorerQuerySpec, build_explorer_gallery_query

    stmt = build_explorer_gallery_query(
        ExplorerQuerySpec(sort="posted_at", direction=direction), {"user_id": 1, "role": "admin"}
    )
    sql = str(stmt.compile(dialect=postgresql.dialect()))
    return sql[sql.rindex("ORDER BY") :]


def test_explorer_posted_at_sort_puts_undated_galleries_last_in_both_directions():
    assert "posted_at DESC NULLS LAST" in _explorer_order_sql("desc")
    assert "posted_at ASC NULLS LAST" in _explorer_order_sql("asc")


def test_explorer_added_at_sort_keeps_plain_order():
    # Only the nullable posted_at column opts into NULLS LAST; indexed sorts stay plain.
    from services.explorer_query import ExplorerQuerySpec, build_explorer_gallery_query

    stmt = build_explorer_gallery_query(ExplorerQuerySpec(sort="added_at"), {"user_id": 1, "role": "admin"})
    sql = str(stmt.compile(dialect=postgresql.dialect()))
    assert "NULLS LAST" not in sql[sql.rindex("ORDER BY") :]
