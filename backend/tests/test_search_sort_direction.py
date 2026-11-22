"""Library search: sort direction (``dir``) and viewer-rating sort.

Cursor walks (first page without cursor, then ``next_cursor``) must visit every
matching gallery exactly once, in the specified order, for every sort key in
both directions. ``rating`` orders by the *viewer's* ``user_ratings`` row, never
by ``galleries.rating`` (E-Hentai source rating).

SQLite (test DB) sorts NULLs last on DESC and first on ASC, so NULL placement
in the emitted SQL is asserted in test_gallery_sort.py / the capture test below.
"""

import base64
import json

import pytest
from sqlalchemy import event, text

# sid, title, pages, posted_at, added_at, content_updated_at, viewer rating, source rating
_ROWS = [
    ("a", "Alpha", 10, "2024-01-01 00:00:00", "2024-02-01 00:00:00", "2024-03-01 00:00:00", 3, 1),
    ("b", "Bravo", 10, "2024-01-01 00:00:00", "2024-02-01 00:00:00", "2024-03-01 00:00:00", 3, 2),
    ("c", "Charlie", 30, "2024-03-01 00:00:00", "2024-05-01 00:00:00", "2024-06-01 00:00:00", 5, 0),
    ("d", "Delta", None, None, "2024-01-15 00:00:00", "2024-01-20 00:00:00", None, 5),
    ("e", "Echo", 5, None, "2024-04-01 00:00:00", "2024-04-02 00:00:00", 1, 4),
    ("f", "Alpha", 20, "2023-06-01 00:00:00", "2023-07-01 00:00:00", "2023-08-01 00:00:00", None, 5),
]
_KEY_INDEX = {"title": 1, "pages": 2, "posted_at": 3, "added_at": 4, "content_updated_at": 5, "rating": 6}


def _ts(v: str | None) -> str | None:
    # '.000000' matches what the ORM binds, so keyset equality works on SQLite.
    return f"{v}.000000" if v else None


async def _seed(db, source: str = "sd", user_id: int = 1) -> dict[str, int]:
    ids: dict[str, int] = {}
    for sid, title, pages, posted, added, cua, mine, src in _ROWS:
        await db.execute(
            text(
                "INSERT INTO galleries (source, source_id, title, pages, download_status, tags_array, "
                "posted_at, added_at, content_updated_at, rating, visibility) "
                "VALUES (:s, :sid, :t, :pg, 'completed', '[]', :p, :a, :c, :r, 'public')"
            ),
            {
                "s": source,
                "sid": sid,
                "t": title,
                "pg": pages,
                "p": _ts(posted),
                "a": _ts(added),
                "c": _ts(cua),
                "r": src,
            },
        )
        await db.commit()
        gid = (
            await db.execute(
                text("SELECT id FROM galleries WHERE source=:s AND source_id=:sid"), {"s": source, "sid": sid}
            )
        ).scalar()
        ids[sid] = gid
        if mine is not None:
            await db.execute(
                text("INSERT INTO user_ratings (user_id, gallery_id, rating) VALUES (:u, :g, :r)"),
                {"u": user_id, "g": gid, "r": mine},
            )
    await db.commit()
    return ids


def _expected(ids: dict[str, int], key: str, direction: str) -> list[int]:
    idx = _KEY_INDEX[key]
    rows = [(ids[r[0]], r[idx]) for r in _ROWS]
    rev = direction == "desc"
    dated = sorted([r for r in rows if r[1] is not None], key=lambda r: (r[1], r[0]), reverse=rev)
    nulls = sorted([r for r in rows if r[1] is None], key=lambda r: r[0], reverse=rev)
    return [r[0] for r in dated + nulls]


async def _walk(client, limit: int, params: dict, q: str = "source:sd") -> list[int]:
    seen: list[int] = []
    p = {"q": q, "limit": limit, **params}
    for _ in range(30):
        r = await client.get("/api/search/", params=p)
        assert r.status_code == 200, r.text
        data = r.json()
        seen.extend(i["id"] for i in data["items"])
        if not data["has_next"]:
            return seen
        p = {**p, "cursor": data["next_cursor"]}
    raise AssertionError("pagination did not terminate")


@pytest.mark.parametrize("limit", [1, 2])
@pytest.mark.parametrize("direction", ["asc", "desc"])
@pytest.mark.parametrize("key", list(_KEY_INDEX))
async def test_search_sort_cursor_walk_visits_all_in_order(client, db_session, key, direction, limit):
    ids = await _seed(db_session)
    seen = await _walk(client, limit, {"sort": key, "dir": direction})
    assert seen == _expected(ids, key, direction)
    assert len(set(seen)) == len(_ROWS)


async def test_search_sort_title_default_direction_is_ascending(client, db_session):
    ids = await _seed(db_session)
    seen = await _walk(client, 3, {"sort": "title"})
    assert seen == _expected(ids, "title", "asc")


async def test_search_sort_rating_default_direction_is_descending(client, db_session):
    ids = await _seed(db_session)
    seen = await _walk(client, 3, {"sort": "rating"})
    assert seen == _expected(ids, "rating", "desc")


async def test_search_rating_sort_uses_viewer_rating_not_source_rating(client, db_session):
    # A: source rating 5 but unrated by the viewer; B: viewer rating 1.
    await db_session.execute(
        text(
            "INSERT INTO galleries (id, source, source_id, title, pages, download_status, tags_array, rating, visibility) "
            "VALUES (901, 'rt', 'a', 'A', 1, 'completed', '[]', 5, 'public'), "
            "(902, 'rt', 'b', 'B', 1, 'completed', '[]', 0, 'public')"
        )
    )
    await db_session.execute(text("INSERT INTO user_ratings (user_id, gallery_id, rating) VALUES (1, 902, 1)"))
    await db_session.commit()

    desc_ids = await _walk(client, 5, {"sort": "rating"}, q="source:rt")
    asc_ids = await _walk(client, 5, {"sort": "rating", "dir": "asc"}, q="source:rt")

    assert desc_ids == [902, 901]
    assert asc_ids == [902, 901]  # unrated last in both directions


async def test_search_rating_sort_ignores_other_users_ratings(client, db_session):
    await db_session.execute(
        text(
            "INSERT INTO galleries (id, source, source_id, title, pages, download_status, tags_array, visibility) "
            "VALUES (911, 'ru', 'a', 'A', 1, 'completed', '[]', 'public'), "
            "(912, 'ru', 'b', 'B', 1, 'completed', '[]', 'public')"
        )
    )
    # User 2 rated A highest; the viewer (user 1) rated only B.
    await db_session.execute(
        text("INSERT INTO user_ratings (user_id, gallery_id, rating) VALUES (2, 911, 5), (1, 912, 2)")
    )
    await db_session.commit()

    seen = await _walk(client, 1, {"sort": "rating"}, q="source:ru")
    assert seen == [912, 911]
    rows = (await client.get("/api/search/", params={"q": "source:ru", "sort": "rating"})).json()["items"]
    assert [i["id"] for i in rows] == [912, 911]
    assert len(rows) == 2  # LEFT JOIN on (user, gallery) never duplicates a gallery


async def test_search_dir_token_overrides_dir_param(client, db_session):
    ids = await _seed(db_session)
    seen = await _walk(client, 2, {"sort": "pages", "dir": "desc"}, q="source:sd dir:asc")
    assert seen == _expected(ids, "pages", "asc")
    seen = await _walk(client, 2, {"dir": "desc"}, q="source:sd sort:title dir:desc")
    assert seen == _expected(ids, "title", "desc")


async def test_search_invalid_dir_falls_back_to_default(client, db_session):
    ids = await _seed(db_session)
    seen = await _walk(client, 2, {"sort": "pages", "dir": "sideways"})
    assert seen == _expected(ids, "pages", "desc")
    seen = await _walk(client, 2, {"sort": "title"}, q="source:sd dir:up")
    assert seen == _expected(ids, "title", "asc")


async def test_search_cursor_direction_mismatch_returns_400(client, db_session):
    await _seed(db_session)
    first = await client.get("/api/search/", params={"q": "source:sd", "sort": "pages", "dir": "desc", "limit": 1})
    cursor = first.json()["next_cursor"]

    r = await client.get(
        "/api/search/", params={"q": "source:sd", "sort": "pages", "dir": "asc", "limit": 1, "cursor": cursor}
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "Cursor sort direction does not match"


def _legacy_signed_cursor(payload: dict) -> str:
    import hashlib
    import hmac

    from routers.search import _cursor_secret

    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"{encoded}.{hmac.new(_cursor_secret(), encoded.encode(), hashlib.sha256).hexdigest()}"


async def test_search_legacy_cursor_without_direction_uses_default(client, db_session):
    ids = await _seed(db_session)
    first = await client.get("/api/search/", params={"q": "source:sd", "sort": "pages", "limit": 1})
    payload = json.loads(base64.urlsafe_b64decode(first.json()["next_cursor"].split(".")[0] + "=="))
    assert payload["d"] == "desc"
    del payload["d"]

    r = await client.get(
        "/api/search/",
        params={"q": "source:sd", "sort": "pages", "limit": 10, "cursor": _legacy_signed_cursor(payload)},
    )
    assert r.status_code == 200, r.text
    got = [i["id"] for i in r.json()["items"]]
    assert got == _expected(ids, "pages", "desc")[1:]

    # A legacy cursor is read as the default direction: asc request must be rejected.
    r = await client.get(
        "/api/search/",
        params={"q": "source:sd", "sort": "pages", "dir": "asc", "cursor": _legacy_signed_cursor(payload)},
    )
    assert r.status_code == 400


async def test_search_cursor_payload_carries_direction_and_null_marker(client, db_session):
    ids = await _seed(db_session)
    r = await client.get("/api/search/", params={"q": "source:sd", "sort": "rating", "dir": "asc", "limit": 4})
    cursor = r.json()["next_cursor"]  # last row on page = 4th = viewer rating 5 (c)
    payload = json.loads(base64.urlsafe_b64decode(cursor.split(".")[0] + "=="))
    assert payload == {"id": ids["c"], "v": "5", "s": "rating", "d": "asc"}

    r = await client.get("/api/search/", params={"q": "source:sd", "sort": "rating", "dir": "asc", "limit": 5})
    payload = json.loads(base64.urlsafe_b64decode(r.json()["next_cursor"].split(".")[0] + "=="))
    assert payload["v"] == ""  # NULL (unrated) row


async def test_search_added_at_asc_emits_index_compatible_order(client, db_session, db_engine):
    await _seed(db_session)
    statements: list[str] = []

    def _capture(conn, cursor, statement, params, context, executemany):
        if "ORDER BY" in statement and "FROM galleries" in statement:
            statements.append(statement)

    event.listen(db_engine.sync_engine, "before_cursor_execute", _capture)
    try:
        for key in ("added_at", "content_updated_at"):
            for direction in ("asc", "desc"):
                first = await client.get(
                    "/api/search/", params={"q": "source:sd", "sort": key, "dir": direction, "limit": 1}
                )
                assert first.status_code == 200
                r = await client.get(
                    "/api/search/",
                    params={
                        "q": "source:sd",
                        "sort": key,
                        "dir": direction,
                        "limit": 1,
                        "cursor": first.json()["next_cursor"],
                    },
                )
                assert r.status_code == 200
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", _capture)

    ordered = [
        s
        for s in statements
        if "galleries.added_at" in s.split("ORDER BY")[-1] or "content_updated_at" in s.split("ORDER BY")[-1]
    ]
    assert len(ordered) == 8, statements
    assert all("NULLS" not in s.split("ORDER BY")[-1] for s in ordered), ordered
    assert sum("added_at ASC, galleries.id ASC" in s for s in ordered) == 2
    assert sum("added_at DESC, galleries.id DESC" in s for s in ordered) == 2
    assert sum("content_updated_at ASC, galleries.id ASC" in s for s in ordered) == 2
    assert sum("content_updated_at DESC, galleries.id DESC" in s for s in ordered) == 2


async def test_search_rating_sort_joins_user_ratings_on_data_query_only(client, db_session, db_engine):
    await _seed(db_session)
    statements: list[str] = []

    def _capture(conn, cursor, statement, params, context, executemany):
        if "FROM galleries" in statement:
            statements.append(statement)

    event.listen(db_engine.sync_engine, "before_cursor_execute", _capture)
    try:
        r = await client.get("/api/search/", params={"q": "source:sd", "sort": "rating", "limit": 2})
        assert r.status_code == 200
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", _capture)

    counts = [s for s in statements if "count(" in s.lower()]
    data = [s for s in statements if "ORDER BY" in s]
    assert counts and all("user_ratings" not in s for s in counts)
    assert data and all("LEFT OUTER JOIN user_ratings" in s and "NULLS LAST" in s for s in data)
