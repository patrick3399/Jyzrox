"""Router tests for the admin hub-remote settings endpoints (/api/novels/remote*).

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


@pytest.fixture(autouse=True)
def _local_protocol(monkeypatch):
    from services import novel_git

    monkeypatch.setattr(novel_git, "_REMOTE_PROTOCOLS", "ssh:file")


@pytest.fixture()
def ssh_home(tmp_path, monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings, "novel_ssh_dir", str(tmp_path / "ssh"))


@pytest.fixture()
def local_urls(monkeypatch):
    """Let absolute local bare-repo paths pass URL validation (ssh-only in production).

    Hostile inputs still go through the real parser, so this never weakens the
    hostile-URL tests (which do not use this fixture).
    """
    from services import novel_remote

    real = novel_remote.parse_remote_url

    def _parse(url):
        if url.startswith("/") and " " not in url and "\n" not in url:
            return novel_remote.RemoteTarget(url, "localhost", None)
        return real(url)

    monkeypatch.setattr(novel_remote, "parse_remote_url", _parse)


def _unrelated_hub(tmp_path):
    other = tmp_path / "other.git"
    other.mkdir()
    _run(other, "init", "--bare", "-b", "main")
    scratch = tmp_path / "scratch"
    _run(tmp_path, "clone", str(other), str(scratch))
    _run(scratch, "config", "user.email", "t@l")
    _run(scratch, "config", "user.name", "t")
    (scratch / "z.md").write_text("z\n")
    _run(scratch, "add", ".")
    _run(scratch, "commit", "-m", "z")
    _run(scratch, "push", "origin", "main")
    return other


def _origin_url(work):
    return subprocess.run(
        ["git", "-C", str(work), "remote", "get-url", "origin"], capture_output=True, text=True
    ).stdout.strip()


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("get", "/api/novels/remote", None),
        ("post", "/api/novels/remote/key", {}),
        ("post", "/api/novels/remote/hostkeys", {"url": "u@h:/p"}),
        ("post", "/api/novels/remote/trust", {"url": "u@h:/p", "fingerprint": "SHA256:x"}),
        ("post", "/api/novels/remote/test", {"url": "u@h:/p"}),
        ("put", "/api/novels/remote", {"url": "u@h:/p"}),
    ],
)
async def test_remote_routes_forbidden_for_member(member_client, novel_repo, ssh_home, method, path, body):
    r = await getattr(member_client, method)(path, **({"json": body} if body is not None else {}))
    assert r.status_code == 403


async def test_get_remote_reports_url_and_never_private_key(admin_client, novel_repo, ssh_home):
    from services import novel_remote

    r = await admin_client.post("/api/novels/remote/key", json={})
    assert r.status_code == 200 and r.json()["public_key"].startswith("ssh-ed25519 ")
    g = (await admin_client.get("/api/novels/remote")).json()
    assert g["url"] == str(novel_repo["bare"]) and g["has_key"] is True and g["repo_exists"] is True
    assert "PRIVATE" not in str(g) and "private" not in str(g).lower()
    private_body = novel_remote.key_path().read_text()
    assert private_body.strip().splitlines()[1] not in r.text


async def test_key_regenerate_requires_flag(admin_client, novel_repo, ssh_home):
    await admin_client.post("/api/novels/remote/key", json={})
    r = await admin_client.post("/api/novels/remote/key", json={})
    assert r.status_code == 409 and r.json()["detail"]["error"] == "key_exists"
    assert (await admin_client.post("/api/novels/remote/key", json={"regenerate": True})).status_code == 200


@pytest.mark.parametrize("url", ["-oProxyCommand=x@h:/p", "ext::sh -c id", "file:///etc/passwd", "u@h:/a b"])
async def test_put_rejects_hostile_url_before_touching_git(admin_client, novel_repo, url, monkeypatch):
    from services import novel_git

    called = []
    monkeypatch.setattr(novel_git, "history_relation", lambda *a, **k: called.append(1))
    monkeypatch.setattr(novel_git, "clone_replace", lambda *a, **k: called.append(2))
    r = await admin_client.put("/api/novels/remote", json={"url": url})
    assert r.status_code == 400 and called == []


@pytest.mark.parametrize("path", ["hostkeys", "trust", "test"])
async def test_other_remote_routes_reject_hostile_url_with_400(admin_client, novel_repo, ssh_home, path, monkeypatch):
    from services import novel_git, novel_remote

    called = []
    monkeypatch.setattr(novel_git, "ls_remote", lambda *a, **k: called.append(1))
    monkeypatch.setattr(novel_remote, "scan_host_keys", lambda *a, **k: called.append(2))
    r = await admin_client.post(
        f"/api/novels/remote/{path}", json={"url": "-oProxyCommand=x@h:/p", "fingerprint": "SHA256:x"}
    )
    assert r.status_code == 400 and called == []


async def test_put_related_hub_only_repoints_origin(local_urls, admin_client, novel_repo, tmp_path):
    mirror = tmp_path / "mirror.git"
    _run(tmp_path, "clone", "--bare", str(novel_repo["bare"]), str(mirror))
    r = await admin_client.put("/api/novels/remote", json={"url": str(mirror)})
    assert r.status_code == 200 and r.json()["mode"] == "set_url"
    assert _origin_url(novel_repo["work"]) == str(mirror)


async def test_put_unrelated_hub_is_refused_and_leaves_clone_untouched(local_urls, admin_client, novel_repo, tmp_path):
    other = _unrelated_hub(tmp_path)
    r = await admin_client.put("/api/novels/remote", json={"url": str(other)})
    assert r.status_code == 409
    d = r.json()["detail"]
    assert d["error"] == "history_unrelated" and d["reason"] == "unrelated" and d["unpushed"] == 0
    assert d["dirty"] is False
    assert (novel_repo["work"] / "作品A" / "第01章.md").exists()
    assert _origin_url(novel_repo["work"]) == str(novel_repo["bare"])


async def test_put_unrelated_with_confirm_reclones_and_reindexes(
    local_urls, admin_client, novel_repo, tmp_path, monkeypatch
):
    other = _unrelated_hub(tmp_path)
    reindex = AsyncMock()
    monkeypatch.setattr("routers.novels._enqueue_reindex", reindex)
    r = await admin_client.put("/api/novels/remote", json={"url": str(other), "confirm_reclone": True})
    assert r.status_code == 200 and r.json()["mode"] == "recloned"
    assert (novel_repo["work"] / "z.md").exists()
    assert not (novel_repo["work"] / "作品A").exists()
    reindex.assert_awaited_once()


async def test_put_without_existing_clone_clones(local_urls, admin_client, tmp_path, monkeypatch):
    from core.config import settings

    hub = _unrelated_hub(tmp_path)
    target = tmp_path / "fresh"
    monkeypatch.setattr(settings, "novel_repo_path", str(target))
    monkeypatch.setattr("routers.novels._enqueue_reindex", AsyncMock())
    r = await admin_client.put("/api/novels/remote", json={"url": str(hub)})
    assert r.status_code == 200 and r.json()["mode"] == "cloned"
    assert (target / "z.md").exists()


async def test_remote_routes_work_while_module_disabled(
    db_session, db_session_factory, mock_redis, novel_repo, ssh_home
):
    async with _novel_client(db_session, db_session_factory, "admin", mock_redis) as ac:
        # Undo the helper's "enabled" override: the flag is unset -> module disabled.
        mock_redis.get = AsyncMock(return_value=None)
        assert (await ac.get("/api/novels/works")).status_code == 404
        assert (await ac.get("/api/novels/remote")).status_code == 200


async def test_put_holds_git_lock(local_urls, admin_client, novel_repo, tmp_path, monkeypatch):
    import routers.novels as rn

    mirror = tmp_path / "mirror.git"
    _run(tmp_path, "clone", "--bare", str(novel_repo["bare"]), str(mirror))
    calls = []
    real = rn._with_git_lock

    async def spy(factory):
        calls.append(1)
        return await real(factory)

    monkeypatch.setattr(rn, "_with_git_lock", spy)
    r = await admin_client.put("/api/novels/remote", json={"url": str(mirror)})
    assert r.status_code == 200 and calls == [1]


async def test_put_unreachable_remote_is_502_and_changes_nothing(local_urls, admin_client, novel_repo, tmp_path):
    r = await admin_client.put("/api/novels/remote", json={"url": str(tmp_path / "missing.git")})
    assert r.status_code == 502
    assert _origin_url(novel_repo["work"]) == str(novel_repo["bare"])


async def test_test_endpoint_reports_ok_and_failure(local_urls, admin_client, novel_repo, tmp_path):
    ok = (await admin_client.post("/api/novels/remote/test", json={"url": str(novel_repo["bare"])})).json()
    assert ok["ok"] is True and ok["empty"] is False
    bad = (await admin_client.post("/api/novels/remote/test", json={"url": str(tmp_path / "missing.git")})).json()
    assert bad["ok"] is False and bad["error"]


async def test_host_trusted_follows_the_typed_url_when_no_clone_exists(admin_client, tmp_path, ssh_home, monkeypatch):
    """Regression: before the first save there is no stored remote, so the trust
    badge used to be hard-wired to False even for an already-trusted host."""
    from core.config import settings
    from services import novel_remote

    monkeypatch.setattr(settings, "novel_repo_path", str(tmp_path / "empty"))
    seen = []

    async def fake_trusted(target):
        seen.append(target.host)
        return target.host == "trusted.example"

    monkeypatch.setattr(novel_remote, "is_host_trusted", fake_trusted)

    trusted = (await admin_client.get("/api/novels/remote", params={"url": "u@trusted.example:/p.git"})).json()
    other = (await admin_client.get("/api/novels/remote", params={"url": "u@other.example:/p.git"})).json()
    bare = (await admin_client.get("/api/novels/remote")).json()

    assert trusted["host_trusted"] is True and trusted["url"] is None
    assert other["host_trusted"] is False
    assert bare["host_trusted"] is False  # nothing stored, nothing typed
    assert seen == ["trusted.example", "other.example"]


async def test_host_trusted_ignores_an_unparsable_typed_url(admin_client, tmp_path, ssh_home, monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings, "novel_repo_path", str(tmp_path / "empty"))
    r = await admin_client.get("/api/novels/remote", params={"url": "-oProxyCommand=x@h:/p"})
    assert r.status_code == 200 and r.json()["host_trusted"] is False
