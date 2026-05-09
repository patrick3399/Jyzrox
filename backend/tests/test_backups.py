import json
from types import SimpleNamespace
from unittest.mock import patch


def _settings(tmp_path):
    return SimpleNamespace(data_backups_path=str(tmp_path), backup_pg_dump_timeout=3600)


async def test_list_backups_returns_manifests(client, tmp_path):
    dump = tmp_path / "jyzrox_db_20260509_010203.sql.gz"
    dump.write_bytes(b"dump")
    manifest = tmp_path / "jyzrox_db_20260509_010203.json"
    manifest.write_text(
        json.dumps(
            {
                "id": "jyzrox_db_20260509_010203",
                "status": "ok",
                "created_at": "2026-05-09T01:02:03+00:00",
                "filename": dump.name,
                "size_bytes": 4,
                "sha256": "abc",
                "app_version": "test",
                "database": "vault",
            }
        )
    )

    with patch("routers.backups.settings", _settings(tmp_path)):
        resp = await client.get("/api/admin/backups/")

    assert resp.status_code == 200
    data = resp.json()
    assert data["path"] == str(tmp_path)
    assert data["backups"][0]["id"] == "jyzrox_db_20260509_010203"
    assert data["backups"][0]["exists"] is True
    assert data["backups"][0]["size_bytes"] == 4


async def test_run_backup_enqueues_job(client, tmp_path):
    with patch("routers.backups.settings", _settings(tmp_path)):
        resp = await client.post("/api/admin/backups/run")

    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"

    from main import app

    app.state.enqueue.assert_called_once()
    call_args = app.state.enqueue.call_args
    assert call_args.args[0] == "database_backup_job"
    assert call_args.kwargs["force"] is True
    assert call_args.kwargs["_job_id"] == "manual:database_backup"


async def test_delete_backup_removes_dump_and_manifest(client, tmp_path):
    dump = tmp_path / "jyzrox_db_20260509_010203.sql.gz"
    dump.write_bytes(b"dump")
    manifest = tmp_path / "jyzrox_db_20260509_010203.json"
    manifest.write_text(json.dumps({"id": "jyzrox_db_20260509_010203", "filename": dump.name}))

    with patch("routers.backups.settings", _settings(tmp_path)):
        resp = await client.delete("/api/admin/backups/jyzrox_db_20260509_010203")

    assert resp.status_code == 200
    assert not dump.exists()
    assert not manifest.exists()


async def test_delete_backup_does_not_follow_manifest_filename_outside_backup_dir(client, tmp_path):
    outside = tmp_path.parent / "outside.sql.gz"
    outside.write_bytes(b"do not delete")
    manifest = tmp_path / "jyzrox_db_20260509_010203.json"
    manifest.write_text(json.dumps({"id": "jyzrox_db_20260509_010203", "filename": "../outside.sql.gz"}))

    with patch("routers.backups.settings", _settings(tmp_path)):
        resp = await client.delete("/api/admin/backups/jyzrox_db_20260509_010203")

    assert resp.status_code == 200
    assert outside.exists()
    assert not manifest.exists()


async def test_backups_require_admin(make_client, tmp_path):
    with patch("routers.backups.settings", _settings(tmp_path)):
        async with make_client(user_id=2, role="member") as ac:
            resp = await ac.get("/api/admin/backups/")

    assert resp.status_code == 403


async def test_download_backup_streams_file_content(client, tmp_path):
    dump = tmp_path / "jyzrox_db_20260509_010203.sql.gz"
    dump.write_bytes(b"fake-gzip-content")
    manifest = tmp_path / "jyzrox_db_20260509_010203.json"
    manifest.write_text(json.dumps({"id": "jyzrox_db_20260509_010203", "filename": dump.name, "status": "ok"}))

    with patch("routers.backups.settings", _settings(tmp_path)):
        resp = await client.get("/api/admin/backups/jyzrox_db_20260509_010203/download")

    assert resp.status_code == 200
    assert resp.content == b"fake-gzip-content"
    assert "attachment" in resp.headers.get("content-disposition", "")


async def test_download_backup_returns_404_when_dump_file_missing(client, tmp_path):
    manifest = tmp_path / "jyzrox_db_20260509_010203.json"
    manifest.write_text(
        json.dumps({"id": "jyzrox_db_20260509_010203", "filename": "jyzrox_db_20260509_010203.sql.gz", "status": "ok"})
    )

    with patch("routers.backups.settings", _settings(tmp_path)):
        resp = await client.get("/api/admin/backups/jyzrox_db_20260509_010203/download")

    assert resp.status_code == 404


async def test_download_backup_rejects_path_traversal_in_backup_id(client, tmp_path):
    with patch("routers.backups.settings", _settings(tmp_path)):
        resp = await client.get("/api/admin/backups/../etc/passwd/download")

    assert resp.status_code in {400, 404}
