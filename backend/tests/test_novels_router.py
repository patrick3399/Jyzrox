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


@pytest.fixture()
def polluted_novel_repo(novel_repo):
    work = novel_repo["work"]
    (work / "作品A" / "Old").mkdir()
    (work / "作品A" / "Old" / "第01章.md").write_text("# 舊版\n", encoding="utf-8")
    (work / "作品A" / "FORMAT.md").write_text("# 格式\n", encoding="utf-8")
    _run(work, "add", ".")
    _run(work, "commit", "-m", "pollute")
    return novel_repo


async def test_chapters_endpoint_excludes_old_dir_and_reports_category_counts(viewer_client, polluted_novel_repo):
    r = await viewer_client.get("/api/novels/works/作品A/chapters")
    assert r.status_code == 200
    body = r.json()
    assert [c["path"] for c in body["chapters"]] == ["作品A/第01章.md"]
    assert body["categories"] == {"extra": 0, "draft": 0, "reference": 1, "scrap": 1}


async def test_files_endpoint_lists_category_and_rejects_unknown(viewer_client, polluted_novel_repo):
    r = await viewer_client.get("/api/novels/works/作品A/files", params={"category": "scrap"})
    assert r.status_code == 200
    assert [f["path"] for f in r.json()["files"]] == ["作品A/Old/第01章.md"]
    bad = await viewer_client.get("/api/novels/works/作品A/files", params={"category": "main"})
    assert bad.status_code == 400


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


async def test_create_new_file_commits_without_base_sha(member_client, novel_repo):
    """create=True writes + commits a brand-new file with no base_sha at all —
    a create has no base revision to be stale against."""
    r = await member_client.put(
        "/api/novels/file",
        json={
            "path": "作品B/第01章.md",
            "content": "# 新作品\n",
            "create": True,
            "message": "create: 作品B/第01章.md",
        },
    )
    assert r.status_code == 200
    got = await member_client.get("/api/novels/file?path=作品B/第01章.md")
    assert got.status_code == 200
    assert "新作品" in got.json()["content"]


async def test_create_ignores_stale_base_sha(member_client, novel_repo):
    """A create must not 409 on a stale/bogus base_sha — base_sha is irrelevant
    for create; only the free-path invariant matters."""
    r = await member_client.put(
        "/api/novels/file",
        json={"path": "作品B/第02章.md", "content": "x\n", "base_sha": "0000000", "create": True},
    )
    assert r.status_code == 200


async def test_create_existing_file_returns_409(member_client, novel_repo):
    """create=True must refuse to clobber an existing chapter (regardless of base_sha)."""
    r = await member_client.put(
        "/api/novels/file",
        json={"path": "作品A/第01章.md", "content": "覆蓋\n", "create": True},
    )
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "file exists"


async def test_create_rejects_traversal(member_client, novel_repo):
    """create=True with an escaping path is rejected before any write."""
    r = await member_client.put(
        "/api/novels/file",
        json={"path": "../evil.md", "content": "x", "create": True},
    )
    assert r.status_code == 400


async def test_create_viewer_forbidden(viewer_client, novel_repo):
    """Creating a file is a write → viewer gets 403."""
    r = await viewer_client.put(
        "/api/novels/file",
        json={"path": "作品C/第01章.md", "content": "x", "create": True},
    )
    assert r.status_code == 403


async def test_reset_forbidden_for_member(member_client, novel_repo):
    # Two clients cannot coexist (they share _app.dependency_overrides), so the
    # member and admin cases are separate tests.
    assert (await member_client.post("/api/novels/reset")).status_code == 403


async def test_reset_allowed_for_admin(admin_client, novel_repo):
    assert (await admin_client.post("/api/novels/reset")).status_code == 200


# ── Knowledge index endpoints (Phase 1 Track A) ──


def _make_indexed_repo(root):
    w = root / "作品A"
    (w / "Setting").mkdir(parents=True)
    (w / "Setting" / "角色-張三.md").write_text(
        "---\ntype: character\naliases: [小三]\ntags: [第一卷]\n---\n# 張三\n設定", encoding="utf-8"
    )
    (w / "01.md").write_text("張三與小三在此。", encoding="utf-8")
    (w / "02.md").write_text("只有張三。", encoding="utf-8")


@pytest.fixture()
def indexed_repo(tmp_path, monkeypatch):
    from core.config import settings

    root = tmp_path / "idx"
    root.mkdir()
    _make_indexed_repo(root)
    monkeypatch.setattr(settings, "novel_repo_path", str(root))
    return str(root)


@pytest.fixture()
async def seed_index(indexed_repo, db_session):
    from services import novel_index

    await novel_index.reindex_all(db_session, indexed_repo)
    await db_session.commit()
    return indexed_repo


async def test_graph_returns_note_and_chapter_nodes(viewer_client, seed_index):
    r = await viewer_client.get("/api/novels/graph")
    assert r.status_code == 200
    body = r.json()
    types = {n["type"] for n in body["nodes"]}
    assert "note" in types and "chapter" in types
    assert any(e["kind"] == "mention" for e in body["edges"])


async def test_notes_filter_by_type(viewer_client, seed_index):
    r = await viewer_client.get("/api/novels/notes?type=character")
    assert r.status_code == 200
    notes = r.json()["notes"]
    assert notes and all(n["note_type"] == "character" for n in notes)


async def test_notes_filter_by_type_excludes_nonmatching(viewer_client, seed_index):
    r = await viewer_client.get("/api/novels/notes?type=location")
    assert r.status_code == 200
    assert r.json()["notes"] == []


async def test_appearances_ordered_by_chapter(viewer_client, seed_index):
    r = await viewer_client.get("/api/novels/notes/appearances", params={"path": "作品A/Setting/角色-張三.md"})
    assert r.status_code == 200
    aps = r.json()["appearances"]
    chapters = [a["chapter_path"] for a in aps]
    assert chapters == sorted(chapters)
    assert chapters == ["作品A/01.md", "作品A/02.md"]


async def test_reindex_requires_admin(viewer_client, indexed_repo):
    r = await viewer_client.post("/api/novels/reindex")
    assert r.status_code == 403


async def test_reindex_as_admin_populates(admin_client, indexed_repo):
    r = await admin_client.post("/api/novels/reindex")
    assert r.status_code == 200
    stats = r.json()["stats"]
    assert stats["notes"] == 1 and stats["mentions"] >= 2


# ── Phase 1.6: index freshness — tree mutations must enqueue novel_index_job ─


def _capture_enqueue(monkeypatch):
    import core.queue

    enqueued = []

    async def _fake_enqueue(job_name, **kwargs):
        enqueued.append((job_name, kwargs))

    monkeypatch.setattr(core.queue, "enqueue", _fake_enqueue)
    return enqueued


async def test_write_success_enqueues_novel_index_job_with_force(member_client, novel_repo, monkeypatch):
    """Without this, an edit from the reader leaves the knowledge index stale
    until the daily 4am cron (Phase 1.6 bug: NOVEL_UPDATED had no consumer)."""
    enqueued = _capture_enqueue(monkeypatch)
    head = (await member_client.get("/api/novels/file?path=作品A/第01章.md")).json()["base_sha"]
    r = await member_client.put(
        "/api/novels/file",
        json={"path": "作品A/第01章.md", "content": "索引要跟上這次編輯\n", "base_sha": head},
    )
    assert r.status_code == 200
    assert ("novel_index_job", {"force": True}) in enqueued


async def test_write_succeeds_even_when_index_enqueue_fails(member_client, novel_repo, monkeypatch):
    """The commit+push already happened; a queue outage must not turn the
    response into a 5xx (the daily cron self-heals the index)."""
    import core.queue

    monkeypatch.setattr(core.queue, "enqueue", AsyncMock(side_effect=RuntimeError("queue down")))
    head = (await member_client.get("/api/novels/file?path=作品A/第01章.md")).json()["base_sha"]
    r = await member_client.put(
        "/api/novels/file",
        json={"path": "作品A/第01章.md", "content": "enqueue 掛了也要 200\n", "base_sha": head},
    )
    assert r.status_code == 200


async def test_rejected_write_does_not_enqueue_novel_index_job(member_client, novel_repo, monkeypatch):
    """A 409 (stale base_sha) mutates nothing — no pointless full reindex."""
    enqueued = _capture_enqueue(monkeypatch)
    r = await member_client.put(
        "/api/novels/file",
        json={"path": "作品A/第01章.md", "content": "x", "base_sha": "0000000"},
    )
    assert r.status_code == 409
    assert enqueued == []


async def test_sync_pull_with_changes_enqueues_novel_index_job(member_client, novel_repo, monkeypatch):
    import routers.novels as rn

    enqueued = _capture_enqueue(monkeypatch)
    monkeypatch.setattr(rn.novel_git, "fetch", AsyncMock())
    monkeypatch.setattr(
        rn.novel_git,
        "status",
        AsyncMock(return_value={"head": "abc", "ahead": 0, "behind": 2, "clean": True, "locked": False}),
    )
    monkeypatch.setattr(rn.novel_git, "pull_ff", AsyncMock(return_value=True))
    r = await member_client.post("/api/novels/sync")
    assert r.status_code == 200
    assert r.json()["pulled"] is True
    assert ("novel_index_job", {"force": True}) in enqueued


async def test_sync_already_up_to_date_does_not_enqueue_novel_index_job(member_client, novel_repo, monkeypatch):
    """pull_ff returns True even when already up to date (ff-only exit 0) —
    the enqueue gate must key on behind>0, not on pull_ff's return value."""
    import routers.novels as rn

    enqueued = _capture_enqueue(monkeypatch)
    monkeypatch.setattr(rn.novel_git, "fetch", AsyncMock())
    monkeypatch.setattr(
        rn.novel_git,
        "status",
        AsyncMock(return_value={"head": "abc", "ahead": 0, "behind": 0, "clean": True, "locked": False}),
    )
    monkeypatch.setattr(rn.novel_git, "pull_ff", AsyncMock(return_value=True))
    r = await member_client.post("/api/novels/sync")
    assert r.status_code == 200
    assert enqueued == []


async def test_reset_enqueues_novel_index_job(admin_client, novel_repo, monkeypatch):
    """reset --hard rewrites the working tree; the index must follow."""
    import routers.novels as rn

    enqueued = _capture_enqueue(monkeypatch)
    monkeypatch.setattr(rn.novel_git, "reset_to_origin", AsyncMock())
    r = await admin_client.post("/api/novels/reset")
    assert r.status_code == 200
    assert ("novel_index_job", {"force": True}) in enqueued
