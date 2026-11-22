"""``sort=rating`` / ``rating:>=N`` use the viewer's own rating (user_ratings).

``galleries.rating`` is only the E-Hentai source rating; ordering or filtering by
it on the Library list and in Explorer ignored what the user actually rated.
"""

from sqlalchemy import text
from sqlalchemy.dialects import postgresql


async def _seed(db, source: str = "vr") -> dict[str, int]:
    """A: source 5, unrated.  B: source 0, mine 1.  C: source 2, mine 4.  D: unrated, source 0.
    Another user (2) rated A and D 5 -- must never leak into user 1's ordering."""
    ids: dict[str, int] = {}
    for sid, src_rating in (("a", 5), ("b", 0), ("c", 2), ("d", 0)):
        await db.execute(
            text(
                "INSERT INTO galleries (source, source_id, title, pages, download_status, tags_array, rating, "
                "visibility) VALUES (:s, :sid, :t, 1, 'completed', '[]', :r, 'public')"
            ),
            {"s": source, "sid": sid, "t": f"G{sid}", "r": src_rating},
        )
        await db.commit()
        ids[sid] = (
            await db.execute(
                text("SELECT id FROM galleries WHERE source=:s AND source_id=:sid"), {"s": source, "sid": sid}
            )
        ).scalar()
    for uid, key, rating in ((1, "b", 1), (1, "c", 4), (2, "a", 5), (2, "d", 5)):
        await db.execute(
            text("INSERT INTO user_ratings (user_id, gallery_id, rating) VALUES (:u, :g, :r)"),
            {"u": uid, "g": ids[key], "r": rating},
        )
    await db.commit()
    return ids


async def test_library_galleries_rating_sort_uses_viewer_rating(client, db_session):
    ids = await _seed(db_session)

    r = await client.get("/api/library/galleries", params={"sort": "rating", "source": "vr"})

    assert r.status_code == 200, r.text
    got = [g["id"] for g in r.json()["galleries"]]
    # Viewer ratings desc (c=4, b=1), then unrated by id desc (d, a). Old code: a(5), c(2), then b/d.
    assert got == [ids["c"], ids["b"], ids["d"], ids["a"]]


async def test_library_galleries_rating_sort_cursor_walk_includes_unrated_tail(client, db_session):
    ids = await _seed(db_session)

    from types import SimpleNamespace

    from services.library_helpers import encode_cursor as _encode_cursor

    # The page-based first request has no next_cursor: open the keyset walk above every rating.
    start = _encode_cursor(SimpleNamespace(id=10**9), "rating", 99)
    seen: list[int] = []
    params = {"sort": "rating", "source": "vr", "limit": 1, "cursor": start}
    for _ in range(10):
        r = await client.get("/api/library/galleries", params=params)
        assert r.status_code == 200, r.text
        data = r.json()
        seen.extend(g["id"] for g in data["galleries"])
        if not data["has_next"]:
            break
        params = {**params, "cursor": data["next_cursor"]}

    assert seen == [ids["c"], ids["b"], ids["d"], ids["a"]]


async def test_explorer_rating_sort_uses_viewer_rating(client, db_session):
    ids = await _seed(db_session)

    async def _query(direction: str) -> list[int]:
        r = await client.post(
            "/api/explorer/query",
            json={"node_kind": "source", "node_id": "vr", "sort": "rating", "direction": direction},
        )
        assert r.status_code == 200, r.text
        return [i["id"] for i in r.json()["items"]]

    assert await _query("desc") == [ids["c"], ids["b"], ids["d"], ids["a"]]
    # Unrated galleries stay last in ascending order too.
    assert await _query("asc") == [ids["b"], ids["c"], ids["d"], ids["a"]]


def test_explorer_rating_sort_orders_by_user_ratings_nulls_last_in_both_directions():
    from services.explorer_query import ExplorerQuerySpec, build_explorer_gallery_query

    for direction, word in (("desc", "DESC"), ("asc", "ASC")):
        stmt = build_explorer_gallery_query(
            ExplorerQuerySpec(sort="rating", direction=direction), {"user_id": 7, "role": "admin"}
        )
        sql = str(stmt.compile(dialect=postgresql.dialect()))
        order = sql[sql.rindex("ORDER BY") :]
        assert "galleries.rating" not in order
        assert f"user_ratings.rating {word} NULLS LAST" in order or f") {word} NULLS LAST" in order
        assert "user_ratings" in sql


async def test_explorer_rating_filter_uses_viewer_rating(client, db_session):
    ids = await _seed(db_session)

    r = await client.post(
        "/api/explorer/query",
        json={"node_kind": "source", "node_id": "vr", "query": "rating:>=3", "sort": "added_at", "direction": "desc"},
    )

    assert r.status_code == 200, r.text
    # Only C (mine 4). Old code matched A (source rating 5) and not C (source 2).
    assert [i["id"] for i in r.json()["items"]] == [ids["c"]]
