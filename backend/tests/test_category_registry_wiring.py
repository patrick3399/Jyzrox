from unittest.mock import AsyncMock, MagicMock

from sqlalchemy import text

from tests.test_library import _insert_gallery


async def _seed(db_session, *names):
    for order, name in enumerate(names, start=1):
        await db_session.execute(
            text("INSERT INTO gallery_categories (name, color, sort_order, is_builtin) VALUES (:n, 'gray', :o, 1)"),
            {"n": name, "o": order},
        )
    await db_session.commit()


async def _category_of(db_session, gallery_id):
    return (await db_session.execute(text("SELECT category FROM galleries WHERE id = :i"), {"i": gallery_id})).scalar()


# ── single PATCH ────────────────────────────────────────────────────────


async def test_patch_category_case_insensitive_hit_stores_registry_name(client, db_session):
    await _seed(db_session, "Cosplay")
    gid = await _insert_gallery(db_session, source="local", source_id="g1", category=None)

    resp = await client.patch("/api/library/galleries/local/g1", json={"category": " cosplay "})

    assert resp.status_code == 200
    assert await _category_of(db_session, gid) == "Cosplay"


async def test_patch_category_miss_stores_null_instead_of_free_text(client, db_session):
    await _seed(db_session, "Cosplay")
    gid = await _insert_gallery(db_session, source="local", source_id="g1", category="Cosplay")

    resp = await client.patch("/api/library/galleries/local/g1", json={"category": "Not In Registry"})

    assert resp.status_code == 200
    assert await _category_of(db_session, gid) is None


async def test_patch_empty_category_clears_to_null(client, db_session):
    await _seed(db_session, "Cosplay")
    gid = await _insert_gallery(db_session, source="local", source_id="g1", category="Cosplay")

    resp = await client.patch("/api/library/galleries/local/g1", json={"category": ""})

    assert resp.status_code == 200
    assert await _category_of(db_session, gid) is None


# ── Workbench bulk edit ─────────────────────────────────────────────────


async def test_bulk_metadata_category_set_resolves_through_registry(client, db_session):
    await _seed(db_session, "Cosplay")
    hit = await _insert_gallery(db_session, source="local", source_id="g1", category=None)
    miss = await _insert_gallery(db_session, source="local", source_id="g2", category="Cosplay")

    resp = await client.post(
        "/api/explorer/operations/metadata",
        json={"gallery_ids": [hit], "fields": {"category": {"mode": "set", "value": "COSPLAY"}}},
    )
    assert resp.status_code == 200, resp.text
    resp = await client.post(
        "/api/explorer/operations/metadata",
        json={"gallery_ids": [miss], "fields": {"category": {"mode": "set", "value": "Nope"}}},
    )
    assert resp.status_code == 200, resp.text

    assert await _category_of(db_session, hit) == "Cosplay"
    assert await _category_of(db_session, miss) is None


# ── batch scan preview / batch start ────────────────────────────────────


async def test_batch_scan_preview_reports_registry_resolution(client, db_session, tmp_path, monkeypatch):
    import routers.import_router as ir

    await _seed(db_session, "Cosplay")
    for category in ("cosplay", "Novel"):
        gallery = tmp_path / category / "artist" / "g"
        gallery.mkdir(parents=True)
        (gallery / "001.jpg").write_bytes(b"x")

    async def _fake_paths():
        return [str(tmp_path)]

    monkeypatch.setattr(ir, "get_all_library_paths", _fake_paths)

    resp = await client.post(
        "/api/import/batch/scan",
        json={"root_dir": str(tmp_path), "pattern": "{category}/{artist}/{title}"},
    )

    assert resp.status_code == 200
    by_raw = {m["category"]: m["category_resolved"] for m in resp.json()["matches"]}
    assert by_raw == {"cosplay": "Cosplay", "Novel": None}


async def test_batch_start_payload_carries_registry_names_and_none_for_misses(client, db_session, mock_redis):
    from unittest.mock import patch

    await _seed(db_session, "Cosplay")
    with (
        patch("routers.import_router._validate_root_dir", AsyncMock(return_value="/mnt/test_lib/root")),
        patch("routers.import_router.core.queue.enqueue", AsyncMock()) as enqueue,
    ):
        resp = await client.post(
            "/api/import/batch/start",
            json={
                "root_dir": "/mnt/test_lib/root",
                "mode": "copy",
                "galleries": [
                    {"path": "/mnt/test_lib/root/a", "title": "A", "category": "cosplay"},
                    {"path": "/mnt/test_lib/root/b", "title": "B", "category": "Nope"},
                ],
            },
        )

    assert resp.status_code == 200, resp.text
    payload = enqueue.await_args.kwargs["galleries"]
    assert [g["category"] for g in payload] == ["Cosplay", None]


# ── worker: scan + batch import ─────────────────────────────────────────


async def test_scan_discovery_binds_registry_name_and_none_for_unregistered_folder(tmp_path, monkeypatch):
    import worker.scan as scan

    async def _resolve(_session, raw):
        return {"cosplay": "Cosplay"}.get(str(raw).lower())

    monkeypatch.setattr(scan, "resolve_category", _resolve)

    async def run(folder):
        current = tmp_path.joinpath(folder, "artist", "g")
        current.mkdir(parents=True)
        session = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = 1
        session.execute.return_value = result
        spec = scan._LibrarySpec(path=str(tmp_path), pattern="{category}/{artist}/{title}", import_mode="link")
        await scan._discover_single_library_dir(session, spec, current)
        return session.execute.await_args.args[1]["category"]

    assert await run("cosplay") == "Cosplay"
    assert await run("Novel") is None
