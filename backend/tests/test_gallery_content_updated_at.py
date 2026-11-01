"""Tests for galleries.content_updated_at ("last updated") sort.

Covers the init.sql / migration 0037 trigger contract and the sort + keyset
cursor wiring in search, library, explorer and artists.
"""

import re
from pathlib import Path

from sqlalchemy import text

REPO = Path(__file__).resolve().parents[2]


def _function_body(sql: str) -> str:
    m = re.search(
        r"FUNCTION\s+bump_gallery_content_updated_at\(\)\s+RETURNS\s+trigger\s+AS\s+\$\$(.*?)\$\$",
        sql,
        re.S | re.I,
    )
    assert m, "bump_gallery_content_updated_at function not found"
    return " ".join(m.group(1).split())


def test_init_sql_and_migration_0037_define_identical_content_updated_trigger():
    init_sql = (REPO / "db" / "init.sql").read_text()
    mig = (REPO / "backend" / "migrations" / "versions" / "0037_gallery_content_updated_at.py").read_text()
    assert _function_body(init_sql) == _function_body(mig)
    for sql in (init_sql, mig):
        norm = " ".join(sql.split())
        assert "BEFORE UPDATE OF pages ON galleries" in norm


def _start_cursor(module, sort="content_updated_at"):
    """Signed bootstrap cursor positioned after every row (far-future, huge id)."""
    from datetime import datetime
    from types import SimpleNamespace

    future = datetime(2099, 1, 1)
    row = SimpleNamespace(
        id=10**9, content_updated_at=future, added_at=future, posted_at=future, rating=0, pages=0, title=""
    )
    return module._encode_cursor(row, sort)


async def _g(db, sid, added, updated, pages=10, artist=None, source="cua"):
    # SQLite compares datetimes as strings: use the ORM's '.ffffff' shape so keyset
    # equality (tie-break) matches what the cursor binds.
    added, updated = f"{added}.000000", f"{updated}.000000"
    await db.execute(
        text(
            "INSERT INTO galleries (source, source_id, title, pages, download_status, tags_array, "
            "added_at, content_updated_at, artist_id, visibility) "
            "VALUES (:s, :sid, :t, :p, 'completed', '[]', :a, :u, :artist, 'public')"
        ),
        {"s": source, "sid": sid, "t": f"G{sid}", "p": pages, "a": added, "u": updated, "artist": artist},
    )
    await db.commit()
    return (
        await db.execute(text("SELECT id FROM galleries WHERE source=:s AND source_id=:sid"), {"s": source, "sid": sid})
    ).scalar()


async def test_sqlite_trigger_bumps_content_updated_at_only_when_pages_increase(db_session):
    gid = await _g(db_session, "t1", "2024-01-01 00:00:00", "2024-01-01 00:00:00", pages=5)
    await db_session.execute(text("UPDATE galleries SET pages = 5 WHERE id=:i"), {"i": gid})
    await db_session.execute(text("UPDATE galleries SET pages = 3 WHERE id=:i"), {"i": gid})
    await db_session.commit()
    val = (await db_session.execute(text("SELECT content_updated_at FROM galleries WHERE id=:i"), {"i": gid})).scalar()
    assert str(val).startswith("2024-01-01")
    await db_session.execute(text("UPDATE galleries SET pages = 9 WHERE id=:i"), {"i": gid})
    await db_session.commit()
    val = (await db_session.execute(text("SELECT content_updated_at FROM galleries WHERE id=:i"), {"i": gid})).scalar()
    assert not str(val).startswith("2024-01-01")


async def test_search_sort_content_updated_at_orders_recently_grown_gallery_first(client, db_session):
    old_added_grown = await _g(db_session, "a", "2023-01-01 00:00:00", "2024-06-01 00:00:00")
    new_added_stale = await _g(db_session, "b", "2024-01-01 00:00:00", "2024-02-01 00:00:00")

    r = await client.get("/api/search/", params={"q": "source:cua sort:content_updated_at"})
    assert r.status_code == 200
    ids = [i["id"] for i in r.json()["items"]]
    assert ids == [old_added_grown, new_added_stale]
    assert r.json()["items"][0]["content_updated_at"]

    r = await client.get("/api/search/", params={"q": "source:cua sort:added_at"})
    assert [i["id"] for i in r.json()["items"]] == [new_added_stale, old_added_grown]


async def test_search_content_updated_at_cursor_paginates_without_duplicates(client, db_session):
    ts = "2024-05-05 00:00:00"
    ids = {await _g(db_session, f"t{i}", "2024-01-01 00:00:00", ts) for i in range(4)}
    ids.add(await _g(db_session, "late", "2024-01-01 00:00:00", "2024-09-09 00:00:00"))

    seen: list[int] = []
    params = {"q": "source:cua sort:content_updated_at", "limit": 1}
    cursor = None
    for _ in range(10):
        p = dict(params)
        import routers.search as search_router

        p["cursor"] = cursor or _start_cursor(search_router)
        r = await client.get("/api/search/", params=p)
        assert r.status_code == 200
        data = r.json()
        seen.extend(i["id"] for i in data["items"])
        cursor = data["next_cursor"]
        if not data["has_next"]:
            break
    assert len(seen) == len(set(seen)), "no duplicates across tied timestamps"
    assert set(seen) == ids, "no gallery skipped"


async def test_library_galleries_sort_content_updated_at_cursor(client, db_session):
    import routers.library as library_router

    a = await _g(db_session, "a", "2023-01-01 00:00:00", "2024-06-01 00:00:00")
    b = await _g(db_session, "b", "2024-01-01 00:00:00", "2024-02-01 00:00:00")
    c = await _g(db_session, "c", "2024-03-01 00:00:00", "2024-02-01 00:00:00")

    r = await client.get(
        "/api/library/galleries",
        params={"sort": "content_updated_at", "limit": 2, "cursor": _start_cursor(library_router)},
    )
    assert r.status_code == 200
    d = r.json()
    assert [g["id"] for g in d["galleries"]] == [a, c]  # tie b/c broken by id DESC
    assert d["next_cursor"]
    r2 = await client.get(
        "/api/library/galleries", params={"sort": "content_updated_at", "limit": 2, "cursor": d["next_cursor"]}
    )
    assert [g["id"] for g in r2.json()["galleries"]] == [b]

    mismatch = await client.get("/api/library/galleries", params={"sort": "added_at", "cursor": d["next_cursor"]})
    assert mismatch.status_code == 400


async def test_explorer_sort_content_updated_at(client, db_session):
    await db_session.execute(
        text("INSERT INTO users (id, username, password_hash, role) VALUES (1, 'admin', 'unused', 'admin')")
    )
    await db_session.commit()
    a = await _g(db_session, "a", "2023-01-01 00:00:00", "2024-06-01 00:00:00")
    b = await _g(db_session, "b", "2024-01-01 00:00:00", "2024-02-01 00:00:00")

    r = await client.post("/api/explorer/query", json={"sort": "content_updated_at", "direction": "desc"})
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert [i["id"] for i in items][:2] == [a, b]
    asc = await client.post("/api/explorer/query", json={"sort": "content_updated_at", "direction": "asc"})
    assert [i["id"] for i in asc.json()["items"]][:2] == [b, a]


async def test_artists_latest_sort_uses_content_updated_at(client, db_session):
    # Artist A added earlier but grew most recently; B added later but stale.
    await _g(db_session, "a1", "2023-01-01 00:00:00", "2024-09-01 00:00:00", artist="cua:A")
    await _g(db_session, "b1", "2024-05-01 00:00:00", "2024-05-02 00:00:00", artist="cua:B")

    r = await client.get("/api/library/artists", params={"sort": "latest"})
    assert r.status_code == 200, r.text
    assert [a["artist_id"] for a in r.json()["artists"]] == ["cua:A", "cua:B"]
