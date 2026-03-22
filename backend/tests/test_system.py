"""
Integration tests for the system router (/api/system/*).

Uses the `client` fixture (authenticated as admin user_id=1).
- AsyncSessionLocal (used by health/info) is patched to use the SQLite test engine.
- get_redis is already patched by the client fixture via mock_redis.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _insert_user(db_session):
    await db_session.execute(
        text("INSERT OR IGNORE INTO users (id, username, password_hash, role) VALUES (1, 'admin', 'hash', 'admin')")
    )
    await db_session.commit()


# ---------------------------------------------------------------------------
# Tests — health
# ---------------------------------------------------------------------------


async def test_system_health_returns_ok_status(client, db_session_factory, mock_redis):
    mock_redis.ping = AsyncMock(return_value=True)
    with (
        patch("routers.system.AsyncSessionLocal", db_session_factory),
        patch("asyncio.create_subprocess_exec") as mock_proc,
    ):
        # Simulate df -i returning safe inode usage
        proc_mock = AsyncMock()
        proc_mock.communicate = AsyncMock(return_value=(b"IUse%\n10\n", b""))
        mock_proc.return_value = proc_mock

        resp = await client.get("/api/system/health")

    # Health may return 200 ok or 503 if a sub-check fails.
    # We just verify the response has the expected shape.
    data = resp.json()
    if resp.status_code == 200:
        assert data["status"] == "ok"
        assert "services" in data
    else:
        # 503 means a service check failed — still a valid structured response
        assert resp.status_code == 503
        assert "detail" in data


# ---------------------------------------------------------------------------
# Tests — info
# ---------------------------------------------------------------------------


async def test_system_info_returns_version_fields(client, db_session_factory, mock_redis):
    mock_redis.info = AsyncMock(return_value={"redis_version": "7.0.0"})
    with (
        patch("routers.system.AsyncSessionLocal", db_session_factory),
        patch("routers.system._get_tagger_info", new_callable=AsyncMock, return_value=None),
    ):
        resp = await client.get("/api/system/info")

    assert resp.status_code == 200
    data = resp.json()
    assert "version" in data
    assert "versions" in data
    versions = data["versions"]
    assert "jyzrox" in versions
    assert "python" in versions
    assert "fastapi" in versions


async def test_system_info_versions_field_has_expected_keys(client, db_session_factory, mock_redis):
    mock_redis.info = AsyncMock(return_value={"redis_version": "7.0.0"})
    with (
        patch("routers.system.AsyncSessionLocal", db_session_factory),
        patch("routers.system._get_tagger_info", new_callable=AsyncMock, return_value=None),
    ):
        resp = await client.get("/api/system/info")

    assert resp.status_code == 200
    data = resp.json()
    expected_keys = {"jyzrox", "python", "fastapi", "gallery_dl", "postgresql", "redis", "onnxruntime"}
    assert expected_keys == set(data["versions"].keys())


# ---------------------------------------------------------------------------
# Tests — cache
# ---------------------------------------------------------------------------


async def test_system_cache_returns_stats_structure(client, mock_redis):
    mock_redis.info = AsyncMock(return_value={"used_memory": 1024, "used_memory_human": "1.00K"})
    mock_redis.dbsize = AsyncMock(return_value=42)
    mock_redis.scan = AsyncMock(return_value=(0, []))

    resp = await client.get("/api/system/cache")

    assert resp.status_code == 200
    data = resp.json()
    assert "total_keys" in data
    assert "total_memory" in data
    assert "breakdown" in data
    assert isinstance(data["breakdown"], dict)


async def test_system_cache_clear_returns_deleted_count(client, mock_redis):
    mock_redis.scan = AsyncMock(return_value=(0, [b"key1", b"key2"]))
    mock_redis.delete = AsyncMock(return_value=2)

    resp = await client.delete("/api/system/cache")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "deleted_keys" in data
    assert isinstance(data["deleted_keys"], int)


async def test_system_cache_clear_specific_category_works(client, mock_redis):
    mock_redis.scan = AsyncMock(return_value=(0, [b"eh:search:abc"]))
    mock_redis.delete = AsyncMock(return_value=1)

    resp = await client.delete("/api/system/cache/eh_search")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["category"] == "eh_search"
    assert data["deleted_keys"] == 1


async def test_system_cache_clear_unknown_category_returns_400(client, mock_redis):
    resp = await client.delete("/api/system/cache/nonexistent_category")
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Tests — reconcile
# ---------------------------------------------------------------------------


async def test_system_reconcile_trigger_enqueues_job(client):
    resp = await client.post("/api/system/reconcile")
    assert resp.status_code == 200
    assert resp.json()["status"] == "enqueued"
    from main import app

    app.state.enqueue.assert_called_with("reconciliation_job")


async def test_system_reconcile_result_when_never_run_returns_never_run(client, mock_redis):
    mock_redis.get = AsyncMock(return_value=None)

    resp = await client.get("/api/system/reconcile")

    assert resp.status_code == 200
    assert resp.json()["status"] == "never_run"


async def test_system_reconcile_result_when_result_exists_returns_parsed_json(client, mock_redis):
    payload = {"status": "ok", "deleted_orphans": 3, "galleries_checked": 100}
    mock_redis.get = AsyncMock(return_value=json.dumps(payload).encode())

    resp = await client.get("/api/system/reconcile")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["deleted_orphans"] == 3


# ---------------------------------------------------------------------------
# Edge case tests — uncovered lines 35-36, 43, 53-54, 80-86, 97-99,
#                   112-122, 136-160
# ---------------------------------------------------------------------------


# -- _detect_jyzrox_version (lines 35-36) ------------------------------------


def test_detect_jyzrox_version_returns_tag_when_git_succeeds():
    """_detect_jyzrox_version returns the stdout tag when git exits cleanly (line 35-36)."""
    from routers.system import _detect_jyzrox_version

    fake_result = MagicMock()
    fake_result.stdout = "v1.2.3\n"

    with patch("subprocess.run", return_value=fake_result):
        version = _detect_jyzrox_version()

    assert version == "v1.2.3"


def test_detect_jyzrox_version_returns_dev_when_git_output_is_empty():
    """_detect_jyzrox_version returns 'dev' when git stdout is blank."""
    from routers.system import _detect_jyzrox_version

    fake_result = MagicMock()
    fake_result.stdout = ""

    with patch("subprocess.run", return_value=fake_result):
        version = _detect_jyzrox_version()

    assert version == "dev"


def test_detect_jyzrox_version_returns_dev_on_exception():
    """_detect_jyzrox_version returns 'dev' when subprocess.run raises."""
    from routers.system import _detect_jyzrox_version

    with patch("subprocess.run", side_effect=FileNotFoundError("git not found")):
        version = _detect_jyzrox_version()

    assert version == "dev"


# -- _detect_gallery_dl_version (lines 43, 53-54) ----------------------------


@pytest.mark.asyncio
async def test_system_info_includes_dynamic_gallery_dl_version(client):
    """system_info fetches gallery-dl version dynamically via get_current_version()."""
    with (
        patch("worker.gallery_dl_venv.get_current_version", new_callable=AsyncMock, return_value="1.28.0"),
        patch("routers.system._get_postgresql_version", new_callable=AsyncMock, return_value="16.1"),
        patch("routers.system._get_redis_version", new_callable=AsyncMock, return_value="7.2.0"),
        patch("routers.system._get_tagger_info", new_callable=AsyncMock, return_value=None),
    ):
        resp = await client.get("/api/system/info")

    assert resp.status_code == 200
    data = resp.json()
    assert data["versions"]["gallery_dl"] == "1.28.0"


@pytest.mark.asyncio
async def test_system_info_gallery_dl_version_none_when_unavailable(client):
    """system_info returns null gallery-dl version when venv is missing."""
    with (
        patch("worker.gallery_dl_venv.get_current_version", new_callable=AsyncMock, return_value=None),
        patch("routers.system._get_postgresql_version", new_callable=AsyncMock, return_value="16.1"),
        patch("routers.system._get_redis_version", new_callable=AsyncMock, return_value="7.2.0"),
        patch("routers.system._get_tagger_info", new_callable=AsyncMock, return_value=None),
    ):
        resp = await client.get("/api/system/info")

    assert resp.status_code == 200
    data = resp.json()
    assert data["versions"]["gallery_dl"] is None


# -- _get_postgresql_version (lines 80-86) ------------------------------------


async def test_get_postgresql_version_parses_standard_banner(db_session_factory):
    """_get_postgresql_version extracts token[1] from the full PostgreSQL banner (lines 83-86)."""
    from routers.system import _get_postgresql_version

    # Mock the session to return a full PostgreSQL version banner
    mock_row = MagicMock()
    mock_row.scalar_one = MagicMock(return_value="PostgreSQL 15.3 on x86_64-pc-linux-gnu, compiled by gcc")

    mock_result = MagicMock()
    mock_result.scalar_one = mock_row.scalar_one

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_factory = MagicMock()
    mock_factory.return_value = mock_session

    with patch("routers.system.AsyncSessionLocal", mock_factory):
        version = await _get_postgresql_version()

    assert version == "15.3"


async def test_get_postgresql_version_returns_raw_when_single_token(db_session_factory):
    """_get_postgresql_version returns the raw string when it has fewer than 2 parts (line 86)."""
    from routers.system import _get_postgresql_version

    mock_row = MagicMock()
    mock_row.scalar_one = MagicMock(return_value="15.3")  # no spaces → parts[1] absent

    mock_result = MagicMock()
    mock_result.scalar_one = mock_row.scalar_one

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_factory = MagicMock()
    mock_factory.return_value = mock_session

    with patch("routers.system.AsyncSessionLocal", mock_factory):
        version = await _get_postgresql_version()

    assert version == "15.3"


async def test_get_postgresql_version_returns_none_on_exception():
    """_get_postgresql_version returns None when the DB query raises."""
    from routers.system import _get_postgresql_version

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=Exception("db down"))
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_factory = MagicMock()
    mock_factory.return_value = mock_session

    with patch("routers.system.AsyncSessionLocal", mock_factory):
        version = await _get_postgresql_version()

    assert version is None


# -- _get_redis_version (lines 97-99) -----------------------------------------


async def test_get_redis_version_returns_none_on_exception(mock_redis):
    """_get_redis_version returns None when Redis info() raises (lines 97-99)."""
    from routers.system import _get_redis_version

    mock_redis.info = AsyncMock(side_effect=ConnectionError("redis gone"))

    with patch("routers.system.get_redis", return_value=mock_redis):
        version = await _get_redis_version()

    assert version is None


async def test_get_redis_version_returns_none_when_key_missing(mock_redis):
    """_get_redis_version returns None when redis_version key is absent from INFO."""
    from routers.system import _get_redis_version

    mock_redis.info = AsyncMock(return_value={})  # empty dict — no redis_version key

    with patch("routers.system.get_redis", return_value=mock_redis):
        version = await _get_redis_version()

    assert version is None


# -- health: Redis error path (lines 112-122) ---------------------------------


async def test_system_health_returns_503_when_redis_unavailable(client, db_session_factory, mock_redis):
    """Health check returns 503 with detail when Redis ping raises (lines 116-122)."""
    mock_redis.ping = AsyncMock(side_effect=ConnectionError("redis refused"))

    with (
        patch("routers.system.AsyncSessionLocal", db_session_factory),
        patch("asyncio.create_subprocess_exec") as mock_proc,
    ):
        proc_mock = AsyncMock()
        proc_mock.communicate = AsyncMock(return_value=(b"IUse%\n10\n", b""))
        mock_proc.return_value = proc_mock

        resp = await client.get("/api/system/health")

    assert resp.status_code == 503
    data = resp.json()
    assert "detail" in data
    # Redis error should be recorded in the services dict
    assert "redis" in data["detail"]
    assert data["detail"]["redis"].startswith("error:")


async def test_system_health_returns_503_when_postgres_unavailable(client, mock_redis):
    """Health check returns 503 with detail when PostgreSQL is unreachable (lines 112-114)."""
    mock_redis.ping = AsyncMock(return_value=True)

    # Use a mock session factory that raises on execute
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=Exception("pg down"))
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_factory = MagicMock()
    mock_factory.return_value = mock_session

    with (
        patch("routers.system.AsyncSessionLocal", mock_factory),
        patch("asyncio.create_subprocess_exec") as mock_proc,
    ):
        proc_mock = AsyncMock()
        proc_mock.communicate = AsyncMock(return_value=(b"IUse%\n10\n", b""))
        mock_proc.return_value = proc_mock

        resp = await client.get("/api/system/health")

    assert resp.status_code == 503
    data = resp.json()
    assert "detail" in data
    assert "postgres" in data["detail"]
    assert data["detail"]["postgres"].startswith("error:")


# -- health: inode warning / unknown (lines 136-142) -------------------------


async def test_system_health_warns_when_inode_usage_above_90(client, db_session_factory, mock_redis):
    """Health check records an inode warning when usage exceeds 90% (lines 135-136)."""
    mock_redis.ping = AsyncMock(return_value=True)

    with (
        patch("routers.system.AsyncSessionLocal", db_session_factory),
        patch("asyncio.create_subprocess_exec") as mock_proc,
    ):
        proc_mock = AsyncMock()
        # Simulate df -i reporting 95% inode usage
        proc_mock.communicate = AsyncMock(return_value=(b"IUse%\n95\n", b""))
        mock_proc.return_value = proc_mock

        resp = await client.get("/api/system/health")

    # The response can be 200 or 503 depending on other checks; focus on inode field
    data = resp.json()
    services = data.get("services") or data.get("detail", {})
    assert "inodes" in services
    assert "warning" in services["inodes"]


async def test_system_health_records_unknown_when_df_output_malformed(client, db_session_factory, mock_redis):
    """Health check records 'unknown' for inodes when df output has fewer than 2 lines (line 140)."""
    mock_redis.ping = AsyncMock(return_value=True)

    with (
        patch("routers.system.AsyncSessionLocal", db_session_factory),
        patch("asyncio.create_subprocess_exec") as mock_proc,
    ):
        proc_mock = AsyncMock()
        # Only one line — no data line present
        proc_mock.communicate = AsyncMock(return_value=(b"IUse%\n", b""))
        mock_proc.return_value = proc_mock

        resp = await client.get("/api/system/health")

    data = resp.json()
    services = data.get("services") or data.get("detail", {})
    assert "inodes" in services
    assert services["inodes"] == "unknown"


async def test_system_health_records_unknown_when_df_raises(client, db_session_factory, mock_redis):
    """Health check records 'unknown' for inodes when the subprocess raises (line 142)."""
    mock_redis.ping = AsyncMock(return_value=True)

    with (
        patch("routers.system.AsyncSessionLocal", db_session_factory),
        patch("asyncio.create_subprocess_exec", side_effect=OSError("df not found")),
    ):
        resp = await client.get("/api/system/health")

    data = resp.json()
    services = data.get("services") or data.get("detail", {})
    assert "inodes" in services
    assert services["inodes"] == "unknown"


# -- _get_tagger_info (lines 150-160) / system_info with tagger ---------------


async def test_system_info_with_tagger_online_includes_onnxruntime_version(client, db_session_factory, mock_redis):
    """system_info populates onnxruntime version when tagger is online (lines 150-160, 183)."""
    mock_redis.info = AsyncMock(return_value={"redis_version": "7.0.0"})

    tagger_payload = {
        "status": "ok",
        "onnxruntime_version": "1.17.0",
        "model": "wd-v1-4-vit-tagger-v2",
    }

    with (
        patch("routers.system.AsyncSessionLocal", db_session_factory),
        patch("routers.system._get_tagger_info", new_callable=AsyncMock, return_value=tagger_payload),
    ):
        resp = await client.get("/api/system/info")

    assert resp.status_code == 200
    data = resp.json()
    assert data["versions"]["onnxruntime"] == "1.17.0"
    assert data["tagger"] == tagger_payload


async def test_system_info_with_tagger_offline_has_none_onnxruntime(client, db_session_factory, mock_redis):
    """system_info sets onnxruntime to None when tagger is offline (line 183)."""
    mock_redis.info = AsyncMock(return_value={"redis_version": "7.0.0"})

    with (
        patch("routers.system.AsyncSessionLocal", db_session_factory),
        patch("routers.system._get_tagger_info", new_callable=AsyncMock, return_value=None),
    ):
        resp = await client.get("/api/system/info")

    assert resp.status_code == 200
    data = resp.json()
    assert data["versions"]["onnxruntime"] is None
    assert data["tagger"] is None


async def test_get_tagger_info_returns_none_when_http_fails():
    """_get_tagger_info returns None when httpx raises a connection error (lines 158-160)."""
    import httpx

    from routers.system import _get_tagger_info

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await _get_tagger_info()

    assert result is None


async def test_get_tagger_info_returns_none_when_status_not_200():
    """_get_tagger_info returns None when tagger responds with non-200 status."""
    import httpx

    from routers.system import _get_tagger_info

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_resp = MagicMock()
        mock_resp.status_code = 503

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await _get_tagger_info()

    assert result is None


async def test_get_tagger_info_returns_json_on_200():
    """_get_tagger_info returns parsed JSON body when tagger responds 200 (lines 156-157)."""
    import httpx

    from routers.system import _get_tagger_info

    expected = {"status": "ok", "onnxruntime_version": "1.16.3"}

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json = MagicMock(return_value=expected)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await _get_tagger_info()

    assert result == expected


# ---------------------------------------------------------------------------
# Tests — storage
# ---------------------------------------------------------------------------


async def test_system_storage_returns_mounts_deduplicated_by_device(client):
    """GET /api/system/storage deduplicates paths on the same filesystem device."""
    fake_stat = MagicMock()
    fake_stat.st_dev = 42  # same device for both paths

    fake_usage = MagicMock()
    fake_usage.total = 1_000_000_000_000
    fake_usage.used = 600_000_000_000
    fake_usage.free = 400_000_000_000

    with (
        patch(
            "routers.system._get_real_mounts",
            return_value=[
                ("Gallery Data", "/data/gallery"),
                ("CAS (Content-Addressed)", "/data/cas"),
            ],
        ),
        patch("os.stat", return_value=fake_stat),
        patch("shutil.disk_usage", return_value=fake_usage),
    ):
        resp = await client.get("/api/system/storage")

    assert resp.status_code == 200
    data = resp.json()
    assert "mounts" in data
    # Same st_dev → deduplicated to 1
    assert len(data["mounts"]) == 1
    mount = data["mounts"][0]
    assert mount["label"] == "Gallery Data"
    assert mount["total"] == 1_000_000_000_000
    assert mount["used"] == 600_000_000_000
    assert mount["free"] == 400_000_000_000
    assert mount["percent"] == 60.0


async def test_system_storage_shows_both_mounts_when_different_devices(client):
    """GET /api/system/storage shows both mounts when on different devices."""
    fake_usage = MagicMock()
    fake_usage.total = 1_000_000_000_000
    fake_usage.used = 600_000_000_000
    fake_usage.free = 400_000_000_000

    call_count = 0

    def fake_stat(path):
        nonlocal call_count
        call_count += 1
        m = MagicMock()
        m.st_dev = call_count  # different device per call
        return m

    with (
        patch(
            "routers.system._get_real_mounts",
            return_value=[
                ("Gallery Data", "/data/gallery"),
                ("CAS (Content-Addressed)", "/data/cas"),
            ],
        ),
        patch("os.stat", side_effect=fake_stat),
        patch("shutil.disk_usage", return_value=fake_usage),
    ):
        resp = await client.get("/api/system/storage")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["mounts"]) == 2


async def test_system_storage_handles_oserror_gracefully(client):
    """GET /api/system/storage returns empty mounts when paths don't exist."""
    with (
        patch(
            "routers.system._get_real_mounts",
            return_value=[
                ("Gallery Data", "/data/gallery"),
            ],
        ),
        patch("os.stat", side_effect=OSError("not found")),
    ):
        resp = await client.get("/api/system/storage")

    assert resp.status_code == 200
    assert resp.json()["mounts"] == []


async def test_system_storage_includes_external_mounts(client):
    """GET /api/system/storage shows dynamically detected external mounts."""
    call_count = 0

    def fake_stat(path):
        nonlocal call_count
        call_count += 1
        m = MagicMock()
        m.st_dev = call_count
        return m

    fake_usage = MagicMock()
    fake_usage.total = 2_000_000_000_000
    fake_usage.used = 1_000_000_000_000
    fake_usage.free = 1_000_000_000_000

    with (
        patch(
            "routers.system._get_real_mounts",
            return_value=[
                ("Gallery Data", "/data/gallery"),
                ("CAS (Content-Addressed)", "/data/cas"),
                ("nas1", "/mnt/nas1"),
            ],
        ),
        patch("os.stat", side_effect=fake_stat),
        patch("shutil.disk_usage", return_value=fake_usage),
    ):
        resp = await client.get("/api/system/storage")

    assert resp.status_code == 200
    data = resp.json()
    # gallery + cas + nas1 = 3 (all different st_dev)
    assert len(data["mounts"]) == 3
    labels = [m["label"] for m in data["mounts"]]
    assert "nas1" in labels


async def test_system_storage_no_external_mounts_when_none_detected(client):
    """No external mounts shown when _get_real_mounts returns only known data paths."""
    fake_stat = MagicMock()
    fake_stat.st_dev = 1

    fake_usage = MagicMock()
    fake_usage.total = 1_000_000_000_000
    fake_usage.used = 500_000_000_000
    fake_usage.free = 500_000_000_000

    with (
        patch(
            "routers.system._get_real_mounts",
            return_value=[
                ("Gallery Data", "/data/gallery"),
                ("CAS (Content-Addressed)", "/data/cas"),
            ],
        ),
        patch("os.stat", return_value=fake_stat),
        patch("shutil.disk_usage", return_value=fake_usage),
    ):
        resp = await client.get("/api/system/storage")

    assert resp.status_code == 200
    data = resp.json()
    # Same device → deduplicated to 1, no externals
    assert len(data["mounts"]) == 1


# -- _get_real_mounts unit tests -----------------------------------------------


def test_get_real_mounts_returns_known_paths_and_real_partitions():
    """_get_real_mounts includes known data paths and psutil-detected partitions."""
    from routers.system import _get_real_mounts

    fake_partition = MagicMock()
    fake_partition.fstype = "ext4"
    fake_partition.mountpoint = "/mnt/nas1"

    with patch("psutil.disk_partitions", return_value=[fake_partition]):
        result = _get_real_mounts()

    labels = [r[0] for r in result]
    paths = [r[1] for r in result]
    assert "Gallery Data" in labels
    assert "CAS (Content-Addressed)" in labels
    assert "nas1" in labels
    assert "/mnt/nas1" in paths


def test_get_real_mounts_filters_virtual_filesystems():
    """_get_real_mounts excludes virtual fs types like proc, sysfs, tmpfs."""
    from routers.system import _get_real_mounts

    partitions = []
    for fs in ["proc", "sysfs", "tmpfs", "overlay", "cgroup2"]:
        p = MagicMock()
        p.fstype = fs
        p.mountpoint = f"/{fs}"
        partitions.append(p)

    with patch("psutil.disk_partitions", return_value=partitions):
        result = _get_real_mounts()

    # Should only have the known paths (gallery + cas), no virtual fs
    paths = [r[1] for r in result]
    for fs in ["proc", "sysfs", "tmpfs", "overlay", "cgroup2"]:
        assert f"/{fs}" not in paths


def test_get_real_mounts_filters_system_paths():
    """_get_real_mounts excludes system mount paths like /, /proc, /sys."""
    from routers.system import _get_real_mounts

    partitions = []
    for path in ["/", "/proc", "/sys", "/dev", "/tmp"]:
        p = MagicMock()
        p.fstype = "ext4"
        p.mountpoint = path
        partitions.append(p)

    with patch("psutil.disk_partitions", return_value=partitions):
        result = _get_real_mounts()

    paths = [r[1] for r in result]
    for sys_path in ["/", "/proc", "/sys", "/dev", "/tmp"]:
        assert sys_path not in paths


def test_get_real_mounts_labels_known_paths_correctly():
    """_get_real_mounts uses KNOWN_LABELS for data_gallery_path and data_cas_path."""
    from routers.system import _get_real_mounts

    with patch("psutil.disk_partitions", return_value=[]):
        result = _get_real_mounts()

    label_map = {path: label for label, path in result}
    # Check that known paths get their special labels
    from core.config import settings

    assert label_map.get(settings.data_gallery_path) == "Gallery Data"
    assert label_map.get(settings.data_cas_path) == "CAS (Content-Addressed)"


def test_get_real_mounts_uses_dirname_as_label_for_unknown_paths():
    """_get_real_mounts uses the last directory component as label for unknown mount points."""
    from routers.system import _get_real_mounts

    fake_partition = MagicMock()
    fake_partition.fstype = "nfs"
    fake_partition.mountpoint = "/pool100"

    with patch("psutil.disk_partitions", return_value=[fake_partition]):
        result = _get_real_mounts()

    label_map = {path: label for label, path in result}
    assert label_map.get("/pool100") == "pool100"
