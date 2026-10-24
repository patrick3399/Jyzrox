import shutil
import stat

import pytest

from services import novel_remote as nr

needs_ssh = pytest.mark.skipif(shutil.which("ssh-keygen") is None, reason="ssh-keygen not installed")


@pytest.fixture()
def ssh_home(tmp_path, monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings, "novel_ssh_dir", str(tmp_path / "ssh"))
    return tmp_path / "ssh"


@pytest.mark.parametrize(
    "url,host,port",
    [
        ("patrick339@192.168.10.201:/mnt/s3610/Git/Novel.git", "192.168.10.201", None),
        ("git@hub.example.com:novel/Novel.git", "hub.example.com", None),
        ("ssh://git@hub.example.com:2222/srv/Novel.git", "hub.example.com", 2222),
        ("ssh://git@hub.example.com/srv/Novel.git", "hub.example.com", None),
    ],
)
def test_parse_accepts_ssh_forms(url, host, port):
    t = nr.parse_remote_url(url)
    assert (t.host, t.port, t.url) == (host, port, url)


@pytest.mark.parametrize(
    "url",
    [
        "",
        "-oProxyCommand=id@host:/x",
        "ext::sh -c id",
        "file:///etc/passwd",
        "http://host/x.git",
        "https://host/x.git",
        "user@host:",
        "user@host:/a b",
        "user@host:/x\nfoo",
        "ssh://user@host:99999/x",
        "ssh://-oProxyCommand=x@host/x",
        "user@-host:/x",
        "/local/path/Novel.git",
    ],
)
def test_parse_rejects_hostile_or_non_ssh(url):
    with pytest.raises(nr.InvalidRemote):
        nr.parse_remote_url(url)


def test_ssh_command_is_pinned_even_without_a_key(ssh_home):
    cmd = nr.ssh_command()
    assert str(ssh_home / "id_ed25519") in cmd
    assert "IdentitiesOnly=yes" in cmd and "StrictHostKeyChecking=yes" in cmd and "BatchMode=yes" in cmd


@needs_ssh
async def test_generate_key_is_private_and_returns_only_public(ssh_home):
    pub = await nr.generate_key(overwrite=False)
    assert pub.startswith("ssh-ed25519 ")
    assert "PRIVATE" not in pub
    mode = stat.S_IMODE(nr.key_path().stat().st_mode)
    assert mode == 0o600
    cmd = nr.ssh_command()
    assert cmd and "StrictHostKeyChecking=yes" in cmd and "BatchMode=yes" in cmd
    assert str(nr.key_path()) in cmd


@needs_ssh
async def test_generate_key_refuses_overwrite_without_flag(ssh_home):
    first = await nr.generate_key(overwrite=False)
    with pytest.raises(nr.KeyExists):
        await nr.generate_key(overwrite=False)
    assert nr.public_key() == first  # untouched
    second = await nr.generate_key(overwrite=True)
    assert second != first


async def test_trust_host_rejects_fingerprint_not_in_fresh_scan(ssh_home, monkeypatch):
    ssh_home.mkdir(parents=True)

    async def fake_scan(target):
        return [{"type": "ed25519", "fingerprint": "SHA256:real", "line": "h ssh-ed25519 AAAA"}]

    monkeypatch.setattr(nr, "scan_host_keys", fake_scan)
    t = nr.parse_remote_url("u@h:/p.git")
    with pytest.raises(nr.FingerprintMismatch):
        await nr.trust_host(t, "SHA256:attacker")
    assert not nr.known_hosts_path().exists() or nr.known_hosts_path().read_text() == ""


async def test_trust_host_appends_matching_line_once(ssh_home, monkeypatch):
    ssh_home.mkdir(parents=True)

    async def fake_scan(target):
        return [{"type": "ed25519", "fingerprint": "SHA256:real", "line": "h ssh-ed25519 AAAA"}]

    monkeypatch.setattr(nr, "scan_host_keys", fake_scan)
    t = nr.parse_remote_url("u@h:/p.git")
    await nr.trust_host(t, "SHA256:real")
    await nr.trust_host(t, "SHA256:real")
    assert nr.known_hosts_path().read_text().splitlines() == ["h ssh-ed25519 AAAA"]
