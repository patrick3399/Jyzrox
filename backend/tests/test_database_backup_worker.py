import gzip
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


class _Pipe:
    def __init__(self):
        self.calls = []

    def set(self, *args):
        self.calls.append(("set", args))
        return self

    def delete(self, *args):
        self.calls.append(("delete", args))
        return self

    async def execute(self):
        return True


class _Redis:
    def __init__(self):
        self.set = AsyncMock(return_value=True)
        self.get = AsyncMock(return_value=None)
        self.delete = AsyncMock(return_value=1)
        self.pipe = _Pipe()

    def pipeline(self):
        return self.pipe


def _settings(tmp_path, retention=14):
    return SimpleNamespace(
        data_backups_path=str(tmp_path),
        backup_retention_count=retention,
        backup_pg_dump_timeout=3600,
        database_url="postgresql+asyncpg://vault:secret@postgres:5432/vault",
    )


async def test_database_backup_job_creates_dump_and_manifest(tmp_path):
    from worker.backup import database_backup_job

    async def fake_dump(path):
        with gzip.open(path, "wb") as f:
            f.write(b"SQL")

    redis = _Redis()
    with (
        patch("worker.backup.settings", _settings(tmp_path)),
        patch("worker.backup._run_pg_dump", new=AsyncMock(side_effect=fake_dump)),
    ):
        result = await database_backup_job({"redis": redis}, force=True)

    assert result["status"] == "ok"
    dump_path = tmp_path / result["filename"]
    manifest_path = tmp_path / f"{result['backup_id']}.json"
    assert dump_path.exists()
    assert manifest_path.exists()
    assert gzip.decompress(dump_path.read_bytes()) == b"SQL"
    manifest = json.loads(manifest_path.read_text())
    assert manifest["status"] == "ok"
    assert manifest["database"] == "vault"
    assert manifest["filename"] == result["filename"]
    assert manifest["sha256"] == result["sha256"]


def test_pg_dump_connection_keeps_password_out_of_url(tmp_path):
    from worker.backup import _pg_dump_connection

    with patch("worker.backup.settings", _settings(tmp_path)):
        url, password = _pg_dump_connection()

    assert "secret" not in url
    assert url == "postgresql://vault@postgres:5432/vault"
    assert password == "secret"


async def test_database_backup_job_removes_tmp_and_records_failure(tmp_path):
    from worker.backup import database_backup_job

    async def fake_dump(path):
        path.write_bytes(b"partial")
        raise RuntimeError("dump failed")

    redis = _Redis()
    with (
        patch("worker.backup.settings", _settings(tmp_path)),
        patch("worker.backup._run_pg_dump", new=AsyncMock(side_effect=fake_dump)),
    ):
        result = await database_backup_job({"redis": redis}, force=True)

    assert result["status"] == "failed"
    assert not list(tmp_path.glob("*.tmp"))
    manifests = list(tmp_path.glob("jyzrox_db_*.json"))
    assert len(manifests) == 1
    assert json.loads(manifests[0].read_text())["error"] == "dump failed"


async def test_database_backup_job_enforces_retention(tmp_path):
    from worker.backup import database_backup_job

    for i in range(3):
        dump = tmp_path / f"jyzrox_db_20260509_00000{i}.sql.gz"
        dump.write_bytes(b"old")
        manifest = tmp_path / f"jyzrox_db_20260509_00000{i}.json"
        manifest.write_text(
            json.dumps(
                {
                    "id": manifest.stem,
                    "status": "ok",
                    "created_at": f"2026-05-09T00:00:0{i}+00:00",
                    "filename": dump.name,
                }
            )
        )

    async def fake_dump(path):
        with gzip.open(path, "wb") as f:
            f.write(b"new")

    redis = _Redis()
    with (
        patch("worker.backup.settings", _settings(tmp_path, retention=2)),
        patch("worker.backup._run_pg_dump", new=AsyncMock(side_effect=fake_dump)),
    ):
        result = await database_backup_job({"redis": redis}, force=True)

    assert result["status"] == "ok"
    successful = [
        json.loads(path.read_text())
        for path in tmp_path.glob("jyzrox_db_*.json")
        if json.loads(path.read_text()).get("status") == "ok"
    ]
    assert len(successful) == 2
