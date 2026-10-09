from sqlalchemy import text

from tests.test_library import _insert_gallery

BASE = "/api/gallery-categories"


async def _seed(db_session, *rows):
    """rows: (name, color, is_builtin)"""
    for order, (name, color, builtin) in enumerate(rows, start=1):
        await db_session.execute(
            text("INSERT INTO gallery_categories (name, color, sort_order, is_builtin) VALUES (:n, :c, :o, :b)"),
            {"n": name, "c": color, "o": order, "b": 1 if builtin else 0},
        )
    await db_session.commit()


async def _category_of(db_session, gallery_id):
    row = await db_session.execute(text("SELECT category FROM galleries WHERE id = :i"), {"i": gallery_id})
    return row.scalar()


# ── list ────────────────────────────────────────────────────────────────


async def test_list_returns_categories_usage_counts_and_palette(client, db_session):
    await _seed(db_session, ("Cosplay", "red", True), ("Novel", "teal", False))
    await _insert_gallery(db_session, source_id="a", category="cosplay")  # case differs: still counted
    await _insert_gallery(db_session, source_id="b", category="Cosplay")
    await _insert_gallery(db_session, source_id="c", category="Novel")

    resp = await client.get(f"{BASE}/")

    assert resp.status_code == 200
    body = resp.json()
    by_name = {c["name"]: c for c in body["categories"]}
    assert by_name["Cosplay"]["gallery_count"] == 2
    assert by_name["Novel"]["gallery_count"] == 1
    assert by_name["Cosplay"]["is_builtin"] is True
    assert "gray" in body["palette"]
    # built-ins first
    assert [c["name"] for c in body["categories"]] == ["Cosplay", "Novel"]


async def test_list_is_readable_by_viewer(make_client, db_session):
    await _seed(db_session, ("Cosplay", "red", True))
    async with make_client(user_id=2, role="viewer") as ac:
        resp = await ac.get(f"{BASE}/")
    assert resp.status_code == 200


# ── create ──────────────────────────────────────────────────────────────


async def test_create_as_member_returns_403(make_client):
    async with make_client(user_id=2, role="member") as ac:
        resp = await ac.post(f"{BASE}/", json={"name": "Novel", "color": "teal"})
    assert resp.status_code == 403


async def test_create_stores_trimmed_name_and_next_sort_order(client, db_session):
    await _seed(db_session, ("Cosplay", "red", True))

    resp = await client.post(f"{BASE}/", json={"name": "  Novel  ", "color": "teal"})

    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Novel"
    assert body["color"] == "teal"
    assert body["is_builtin"] is False
    assert body["sort_order"] == 2
    assert body["gallery_count"] == 0


async def test_create_duplicate_differing_only_in_case_returns_409(client, db_session):
    await _seed(db_session, ("Cosplay", "red", True))
    resp = await client.post(f"{BASE}/", json={"name": "cosplay"})
    assert resp.status_code == 409


async def test_create_name_with_path_separator_returns_422(client):
    assert (await client.post(f"{BASE}/", json={"name": "a/b"})).status_code == 422
    assert (await client.post(f"{BASE}/", json={"name": "a\\b"})).status_code == 422


async def test_create_blank_or_overlong_name_returns_422(client):
    assert (await client.post(f"{BASE}/", json={"name": "   "})).status_code == 422
    assert (await client.post(f"{BASE}/", json={"name": "x" * 65})).status_code == 422


async def test_create_reserved_uncategorized_token_returns_422(client):
    resp = await client.post(f"{BASE}/", json={"name": "__Uncategorized__"})
    assert resp.status_code == 422


async def test_create_unknown_palette_color_returns_422(client):
    resp = await client.post(f"{BASE}/", json={"name": "Novel", "color": "chartreuse"})
    assert resp.status_code == 422


# ── patch color ─────────────────────────────────────────────────────────


async def test_patch_color_updates_custom_category(client, db_session):
    await _seed(db_session, ("Novel", "teal", False))
    cid = (await client.get(f"{BASE}/")).json()["categories"][0]["id"]

    resp = await client.patch(f"{BASE}/{cid}", json={"color": "indigo"})

    assert resp.status_code == 200
    assert resp.json()["color"] == "indigo"


async def test_patch_color_on_builtin_returns_403(client, db_session):
    await _seed(db_session, ("Cosplay", "red", True))
    cid = (await client.get(f"{BASE}/")).json()["categories"][0]["id"]
    resp = await client.patch(f"{BASE}/{cid}", json={"color": "indigo"})
    assert resp.status_code == 403


async def test_patch_unknown_color_returns_422_and_unknown_id_404(client, db_session):
    await _seed(db_session, ("Novel", "teal", False))
    cid = (await client.get(f"{BASE}/")).json()["categories"][0]["id"]
    assert (await client.patch(f"{BASE}/{cid}", json={"color": "nope"})).status_code == 422
    assert (await client.patch(f"{BASE}/9999", json={"color": "teal"})).status_code == 404


# ── delete ──────────────────────────────────────────────────────────────


async def test_delete_custom_category_makes_matching_galleries_uncategorized(client, db_session):
    await _seed(db_session, ("Novel", "teal", False), ("Cosplay", "red", True))
    cid = (await client.get(f"{BASE}/")).json()["categories"][1]["id"]  # custom sorts after built-in
    g_exact = await _insert_gallery(db_session, source_id="a", category="Novel")
    g_case = await _insert_gallery(db_session, source_id="b", category="novel")
    g_other = await _insert_gallery(db_session, source_id="c", category="Cosplay")
    await db_session.execute(text("UPDATE galleries SET deleted_at = CURRENT_TIMESTAMP WHERE id = :i"), {"i": g_case})
    await db_session.commit()

    resp = await client.delete(f"{BASE}/{cid}")

    assert resp.status_code == 200
    assert resp.json() == {"deleted": "Novel", "galleries_cleared": 2}
    assert await _category_of(db_session, g_exact) is None
    assert await _category_of(db_session, g_case) is None  # trashed rows are cleared too
    assert await _category_of(db_session, g_other) == "Cosplay"
    remaining = [c["name"] for c in (await client.get(f"{BASE}/")).json()["categories"]]
    assert remaining == ["Cosplay"]


async def test_delete_builtin_returns_403_and_keeps_galleries(client, db_session):
    await _seed(db_session, ("Cosplay", "red", True))
    cid = (await client.get(f"{BASE}/")).json()["categories"][0]["id"]
    gid = await _insert_gallery(db_session, source_id="a", category="Cosplay")

    resp = await client.delete(f"{BASE}/{cid}")

    assert resp.status_code == 403
    assert await _category_of(db_session, gid) == "Cosplay"


async def test_delete_unknown_id_returns_404(client):
    assert (await client.delete(f"{BASE}/9999")).status_code == 404


async def test_delete_as_member_returns_403(make_client, db_session):
    await _seed(db_session, ("Novel", "teal", False))
    async with make_client(user_id=2, role="member") as ac:
        assert (await ac.delete(f"{BASE}/1")).status_code == 403


# ── backfill from folders ───────────────────────────────────────────────


async def _library(db_session, path, pattern):
    await db_session.execute(
        text("INSERT INTO library_paths (path, pattern, import_mode) VALUES (:p, :pat, 'link')"),
        {"p": path, "pat": pattern},
    )
    await db_session.commit()


async def _local(db_session, source_id, library_path, category=None):
    return await _insert_gallery(
        db_session,
        source="local",
        source_id=source_id,
        category=category,
        library_path=library_path,
        import_mode="link",
    )


async def test_backfill_dry_run_counts_matches_without_writing(client, db_session):
    await _seed(db_session, ("Cosplay", "red", True))
    await _library(db_session, "/lib", "{category}/{artist}/{_}/{title}")
    gid = await _local(db_session, "cosplay/artist/x/t", "/lib")

    resp = await client.post(f"{BASE}/backfill", json={"dry_run": True})

    assert resp.json() == {"dry_run": True, "matched": 1, "applied": 0}
    assert await _category_of(db_session, gid) is None


async def test_backfill_apply_writes_registry_name_for_uncategorized_only(client, db_session):
    await _seed(db_session, ("Cosplay", "red", True))
    await _library(db_session, "/lib", "{category}/{artist}/{_}/{title}")
    empty = await _local(db_session, "cosplay/a/x/t1", "/lib", category=None)
    blank = await _local(db_session, "Cosplay/a/x/t2", "/lib", category="")
    already = await _local(db_session, "Cosplay/a/x/t3", "/lib", category="Manga")
    miss = await _local(db_session, "Unknown/a/x/t4", "/lib")

    resp = await client.post(f"{BASE}/backfill", json={"dry_run": False})

    assert resp.json() == {"dry_run": False, "matched": 2, "applied": 2}
    assert await _category_of(db_session, empty) == "Cosplay"
    assert await _category_of(db_session, blank) == "Cosplay"
    assert await _category_of(db_session, already) == "Manga"
    assert await _category_of(db_session, miss) is None


async def test_backfill_ignores_libraries_whose_pattern_has_no_leading_category(client, db_session):
    await _seed(db_session, ("Cosplay", "red", True))
    await _library(db_session, "/artists", "{artist}/{title}")  # first segment is an artist here
    gid = await _local(db_session, "Cosplay/title", "/artists")

    resp = await client.post(f"{BASE}/backfill", json={"dry_run": False})

    assert resp.json()["matched"] == 0
    assert await _category_of(db_session, gid) is None


async def test_backfill_skips_trashed_and_manually_cleared_galleries(client, db_session):
    await _seed(db_session, ("Cosplay", "red", True))
    await _library(db_session, "/lib", "{category}/{artist}/{_}/{title}")
    trashed = await _local(db_session, "Cosplay/a/x/t1", "/lib")
    cleared = await _local(db_session, "Cosplay/a/x/t2", "/lib")
    await db_session.execute(text("UPDATE galleries SET deleted_at = CURRENT_TIMESTAMP WHERE id = :i"), {"i": trashed})
    await db_session.execute(
        text(
            "INSERT INTO gallery_metadata_field_states (gallery_id, field_name, origin, locked) "
            "VALUES (:i, 'category', 'manual', 1)"
        ),
        {"i": cleared},
    )
    await db_session.commit()

    resp = await client.post(f"{BASE}/backfill", json={"dry_run": False})

    assert resp.json()["matched"] == 0
    assert await _category_of(db_session, trashed) is None
    assert await _category_of(db_session, cleared) is None


async def test_backfill_as_member_returns_403(make_client):
    async with make_client(user_id=2, role="member") as ac:
        assert (await ac.post(f"{BASE}/backfill", json={})).status_code == 403
