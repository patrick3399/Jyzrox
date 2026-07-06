"""Router tests for /api/novels (read/query/progress/preferences side, Task 5).

Uses a real tmp git repo pointed at by settings.novel_repo_path, plus a
role-parametrizable client that overrides require_auth (require_role depends on
require_auth, so overriding it alone drives RBAC) and patches
routers.novels.async_session onto the SQLite test factory.
"""

import subprocess
import sys
from contextlib import ExitStack, asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest

_conftest = sys.modules.get("conftest") or sys.modules.get("tests.conftest")
assert _conftest is not None, "conftest module not found in sys.modules"
_app = _conftest._app
_fake_get_db = _conftest._fake_get_db


def _run(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture()
def novel_repo(tmp_path, monkeypatch):
    """Real bare origin + working clone with one work/chapter; patch settings."""
    from core.config import settings

    bare = tmp_path / "origin.git"
    bare.mkdir()
    _run(bare, "init", "--bare", "-b", "main")
    work = tmp_path / "work"
    _run(tmp_path, "clone", str(bare), str(work))
    _run(work, "config", "user.email", "jyzrox@local")
    _run(work, "config", "user.name", "Jyzrox")
    (work / "作品A").mkdir()
    (work / "作品A" / "第01章.md").write_text("# 第一章\n\n### 幕一\n\n正文 [[張三]]。\n", encoding="utf-8")
    _run(work, "add", ".")
    _run(work, "commit", "-m", "init")
    _run(work, "push", "origin", "main")
    monkeypatch.setattr(settings, "novel_repo_path", str(work))
    return {"bare": bare, "work": work}


@asynccontextmanager
async def _novel_client(db_session, db_session_factory, role, mock_redis):
    from httpx import ASGITransport, AsyncClient

    from core.auth import require_auth

    async def _override_get_db():
        yield db_session

    async def _override_require_auth():
        return {"user_id": 1, "role": role}

    # Novel feature flag defaults OFF; enable it for the normal-operation client
    # so the router-level gate lets requests through (mirrors an admin toggle-on).
    _orig_redis_get = mock_redis.get

    async def _get_novel_enabled(key):
        if key == "setting:novel_enabled":
            return b"1"
        return await _orig_redis_get(key)

    mock_redis.get = AsyncMock(side_effect=_get_novel_enabled)

    _app.dependency_overrides[_fake_get_db] = _override_get_db
    _app.dependency_overrides[require_auth] = _override_require_auth
    patches = [
        patch("routers.novels.async_session", db_session_factory),
        patch("routers.novels.get_redis", return_value=mock_redis),
        patch("core.redis_client.get_redis", return_value=mock_redis),
        patch("core.rate_limit.get_redis", return_value=mock_redis),
        patch("core.rate_limit.check_rate_limit", new_callable=AsyncMock),
    ]
    try:
        with ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            transport = ASGITransport(app=_app, raise_app_exceptions=False)
            async with AsyncClient(
                transport=transport,
                base_url="http://test",
                cookies={"csrf_token": "test-csrf"},
                headers={"X-CSRF-Token": "test-csrf"},
            ) as ac:
                yield ac
    finally:
        _app.dependency_overrides.clear()


@pytest.fixture()
async def viewer_client(db_session, db_session_factory, mock_redis):
    async with _novel_client(db_session, db_session_factory, "viewer", mock_redis) as ac:
        yield ac


@pytest.fixture()
async def member_client(db_session, db_session_factory, mock_redis):
    async with _novel_client(db_session, db_session_factory, "member", mock_redis) as ac:
        yield ac


@pytest.fixture()
async def admin_client(db_session, db_session_factory, mock_redis):
    async with _novel_client(db_session, db_session_factory, "admin", mock_redis) as ac:
        yield ac


async def test_list_works_returns_folders(viewer_client, novel_repo):
    r = await viewer_client.get("/api/novels/works")
    assert r.status_code == 200
    assert any(w["name"] == "作品A" for w in r.json()["works"])


async def test_novel_endpoints_return_404_when_flag_disabled(viewer_client, novel_repo, mock_redis):
    """Redis override setting:novel_enabled=0 → router gate returns 404."""

    async def _disabled(key):
        if key == "setting:novel_enabled":
            return b"0"
        return None

    mock_redis.get = AsyncMock(side_effect=_disabled)
    r = await viewer_client.get("/api/novels/works")
    assert r.status_code == 404


async def test_novel_endpoints_disabled_by_default_without_redis_override(viewer_client, novel_repo, mock_redis):
    """No Redis override → falls back to config default, which is OFF → 404."""
    mock_redis.get = AsyncMock(return_value=None)
    r = await viewer_client.get("/api/novels/works")
    assert r.status_code == 404


async def test_read_file_returns_content_and_base_sha(viewer_client, novel_repo):
    r = await viewer_client.get("/api/novels/file?path=作品A/第01章.md")
    assert r.status_code == 200
    body = r.json()
    assert "正文" in body["content"]
    assert len(body["base_sha"]) >= 7
    assert body["acts"][0]["title"] == "幕一"
    assert body["backlinks"] == ["張三"]


async def test_read_file_rejects_traversal(viewer_client, novel_repo):
    r = await viewer_client.get("/api/novels/file?path=../../etc/passwd")
    assert r.status_code == 400


async def test_search_returns_hits(viewer_client, novel_repo):
    r = await viewer_client.get("/api/novels/search?q=正文")
    assert r.status_code == 200
    hits = r.json()["hits"]
    assert hits and hits[0]["path"] == "作品A/第01章.md"


async def test_status_reports_repo_state(viewer_client, novel_repo):
    r = await viewer_client.get("/api/novels/status")
    assert r.status_code == 200
    assert r.json()["locked"] is False


async def test_progress_roundtrip(viewer_client, novel_repo):
    put = await viewer_client.put("/api/novels/progress?path=作品A/第01章.md", json={"position": "act:0|offset:12"})
    assert put.status_code == 200
    got = await viewer_client.get("/api/novels/progress?path=作品A/第01章.md")
    assert got.json()["position"] == "act:0|offset:12"


async def test_viewer_cannot_write(viewer_client, novel_repo):
    r = await viewer_client.put(
        "/api/novels/file",
        json={"path": "作品A/第01章.md", "content": "x", "base_sha": "deadbeef"},
    )
    assert r.status_code == 403


async def test_stale_base_sha_returns_409(member_client, novel_repo):
    r = await member_client.put(
        "/api/novels/file",
        json={"path": "作品A/第01章.md", "content": "x", "base_sha": "0000000"},
    )
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "stale base_sha"


async def test_write_success_commits_and_emits(member_client, novel_repo):
    import core.events

    emitted = []

    async def _fake_emit(evt, **kw):
        emitted.append(evt)

    with patch.object(core.events, "emit_safe", _fake_emit):
        head = (await member_client.get("/api/novels/file?path=作品A/第01章.md")).json()["base_sha"]
        r = await member_client.put(
            "/api/novels/file",
            json={
                "path": "作品A/第01章.md",
                "content": "改寫後的正文\n",
                "base_sha": head,
                "message": "edit: 作品A/第01章.md",
            },
        )
    assert r.status_code == 200
    assert r.json()["pushed"] is True
    assert core.events.EventType.NOVEL_UPDATED in emitted
    # bare origin received the commit
    log = await member_client.get("/api/novels/file/history?path=作品A/第01章.md")
    assert log.json()["commits"][0]["message"] == "edit: 作品A/第01章.md"


async def test_write_rechecks_head_under_git_lock(member_client, novel_repo, monkeypatch):
    """A commit that lands after the client read base_sha but before the write
    serializes must be caught as stale — the optimistic-lock check runs under
    the git lock, not before it (otherwise it is a lost-update TOCTOU)."""
    import routers.novels as rn

    work = novel_repo["work"]
    head = (await member_client.get("/api/novels/file?path=作品A/第01章.md")).json()["base_sha"]

    real_acquire = rn.acquire_lock

    async def racing_acquire(r, key, ttl=60):
        # Simulate a concurrent commit advancing HEAD at lock-acquire time.
        (work / "作品A" / "第01章.md").write_text("concurrent\n", encoding="utf-8")
        _run(work, "commit", "-am", "concurrent edit")
        return await real_acquire(r, key, ttl)

    monkeypatch.setattr(rn, "acquire_lock", racing_acquire)
    r = await member_client.put(
        "/api/novels/file",
        json={"path": "作品A/第01章.md", "content": "mine\n", "base_sha": head},
    )
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "stale base_sha"


async def test_write_unchanged_content_is_noop_not_500(member_client, novel_repo):
    """Saving the file with its current content must return 200, not 500."""
    body = await member_client.get("/api/novels/file?path=作品A/第01章.md")
    doc = body.json()
    r = await member_client.put(
        "/api/novels/file",
        json={"path": "作品A/第01章.md", "content": doc["content"], "base_sha": doc["base_sha"]},
    )
    assert r.status_code == 200


async def test_write_to_locked_repo_returns_409(member_client, novel_repo):
    (novel_repo["work"] / ".jyzrox-locked").write_text("conflict\n", encoding="utf-8")
    head = (await member_client.get("/api/novels/file?path=作品A/第01章.md")).json()["base_sha"]
    r = await member_client.put(
        "/api/novels/file",
        json={"path": "作品A/第01章.md", "content": "x\n", "base_sha": head},
    )
    assert r.status_code == 409
    assert "locked" in str(r.json()["detail"])


async def test_file_diff_rejects_arg_injection(viewer_client, novel_repo, tmp_path):
    """rev=--output=<path> must be rejected (400), never write an arbitrary file."""
    sentinel = tmp_path / "pwned.txt"
    r = await viewer_client.get(f"/api/novels/file/diff?path=作品A/第01章.md&rev=--output={sentinel}")
    assert r.status_code == 400
    assert not sentinel.exists()


async def test_file_history_rejects_traversal(viewer_client, novel_repo):
    r = await viewer_client.get("/api/novels/file/history?path=../../etc/passwd")
    assert r.status_code == 400


async def test_reset_forbidden_for_member(member_client, novel_repo):
    # Two clients cannot coexist (they share _app.dependency_overrides), so the
    # member and admin cases are separate tests.
    assert (await member_client.post("/api/novels/reset")).status_code == 403


async def test_reset_allowed_for_admin(admin_client, novel_repo):
    assert (await admin_client.post("/api/novels/reset")).status_code == 200
