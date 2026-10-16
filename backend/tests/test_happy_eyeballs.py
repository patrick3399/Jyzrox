"""Tests for the Happy Eyeballs sitecustomize injected into gallery-dl subprocesses."""

import errno
import http.server
import importlib.util
import os
import socket
import threading
import time
from pathlib import Path

import pytest

_SITE_DIR = Path(__file__).resolve().parent.parent / "plugins" / "builtin" / "gallery_dl" / "_subprocess_site"


def _ipv6_loopback_available() -> bool:
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as s:
            s.bind(("::1", 0))
        return True
    except OSError:
        return False


needs_ipv6_loopback = pytest.mark.skipif(not _ipv6_loopback_available(), reason="no IPv6 loopback")


@pytest.fixture
def he(monkeypatch):
    """Load the module under an alias so the real ``sitecustomize`` stays untouched.

    Loading it installs the patch, as it does in gallery-dl; urllib3 is put
    back afterwards so no other test runs against it.
    """
    import urllib3.util.connection as u3conn

    monkeypatch.setattr(u3conn, "create_connection", u3conn.create_connection)
    spec = importlib.util.spec_from_file_location("sitecustomize_under_test", _SITE_DIR / "sitecustomize.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _BlackholeSocket:
    """A connect attempt whose SYN is never answered: it never becomes writable."""

    instances: list[_BlackholeSocket] = []

    def __init__(self, family, type_=socket.SOCK_STREAM, proto=0):
        self.family = family
        self._read_fd, self._write_fd = os.pipe()
        self.closed = False
        self.options: list[tuple] = []
        self.bound = None
        _BlackholeSocket.instances.append(self)

    def setsockopt(self, *args):
        self.options.append(args)

    def bind(self, address):
        self.bound = address

    def setblocking(self, flag):
        pass

    def connect_ex(self, address):
        return errno.EINPROGRESS

    def fileno(self):
        return self._read_fd  # the read end of a pipe is never writable

    def getsockopt(self, *args):
        return 0

    def close(self):
        if not self.closed:
            os.close(self._read_fd)
            os.close(self._write_fd)
            self.closed = True


@pytest.fixture
def listener():
    """Start TCP listeners on loopback; returns (port, {family: accepted_count})."""
    sockets = []
    accepted: dict[int, int] = {}

    def _start(families, port=0):
        for family, host in families:
            s = socket.socket(family, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if family == socket.AF_INET6:
                s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            s.bind((host, port))
            port = s.getsockname()[1]
            s.listen(8)
            sockets.append(s)
        return port

    yield _start, accepted
    for s in sockets:
        s.close()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _addrinfo(*entries):
    """getaddrinfo() stand-in returning ``entries`` as (family, host) in order."""

    def _fake(host, port, family=0, type_=0, proto=0, flags=0):
        out = []
        for fam, addr in entries:
            sockaddr = (addr, port, 0, 0) if fam == socket.AF_INET6 else (addr, port)
            out.append((fam, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr))
        return out

    return _fake


def _factory_blackholing(*families):
    def _make(family, type_=socket.SOCK_STREAM, proto=0):
        if family in families:
            return _BlackholeSocket(family, type_, proto)
        return socket.socket(family, type_, proto)

    return _make


# ── connection racing ──


def test_blackholed_ipv6_falls_back_to_reachable_ipv4_within_one_second(he, listener, monkeypatch):
    """IPv6 that never answers must not cost a whole connect timeout per address."""
    start, _ = listener
    port = start([(socket.AF_INET, "127.0.0.1")])
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        _addrinfo((socket.AF_INET6, "2001:db8::1"), (socket.AF_INET6, "2001:db8::2"), (socket.AF_INET, "127.0.0.1")),
    )
    monkeypatch.setattr(he, "_socket_factory", _factory_blackholing(socket.AF_INET6))
    _BlackholeSocket.instances.clear()

    t = time.monotonic()
    sock = he.create_connection(("example.test", port), timeout=30)
    elapsed = time.monotonic() - t
    try:
        assert sock.family == socket.AF_INET
        assert sock.getpeername() == ("127.0.0.1", port)
        # Second attempt (IPv4, interleaved) starts after one ATTEMPT_DELAY.
        assert elapsed < 1.0
        # The losing attempts are closed, not leaked.
        assert all(b.closed for b in _BlackholeSocket.instances)
    finally:
        sock.close()


@needs_ipv6_loopback
def test_reachable_ipv6_is_used_when_it_answers_first(he, listener, monkeypatch):
    start, _ = listener
    port = start([(socket.AF_INET6, "::1"), (socket.AF_INET, "127.0.0.1")])
    monkeypatch.setattr(socket, "getaddrinfo", _addrinfo((socket.AF_INET6, "::1"), (socket.AF_INET, "127.0.0.1")))

    sock = he.create_connection(("example.test", port), timeout=5)
    try:
        assert sock.family == socket.AF_INET6
    finally:
        sock.close()


def test_single_family_host_is_handed_to_the_original_urllib3_function(he, monkeypatch):
    """Hosts without both families keep urllib3's own behaviour exactly."""
    calls = []
    monkeypatch.setattr(he, "_original", lambda *args: calls.append(args) or "original-socket")
    monkeypatch.setattr(socket, "getaddrinfo", _addrinfo((socket.AF_INET, "192.0.2.1"), (socket.AF_INET, "192.0.2.2")))

    assert he.create_connection(("example.test", 443), 7, None, None) == "original-socket"
    assert calls == [(("example.test", 443), 7, None, None)]


@needs_ipv6_loopback
def test_refused_first_address_starts_the_next_attempt_immediately(he, listener, monkeypatch):
    start, _ = listener
    port = start([(socket.AF_INET, "127.0.0.1")])  # nothing listens on ::1 → refused
    monkeypatch.setattr(socket, "getaddrinfo", _addrinfo((socket.AF_INET6, "::1"), (socket.AF_INET, "127.0.0.1")))
    monkeypatch.setattr(he, "ATTEMPT_DELAY", 5.0)

    t = time.monotonic()
    sock = he.create_connection(("example.test", port), timeout=5)
    try:
        assert sock.family == socket.AF_INET
        assert time.monotonic() - t < 1.0  # did not sit out the 5 s attempt delay
    finally:
        sock.close()


@needs_ipv6_loopback
def test_all_attempts_failing_raise_the_last_error(he, monkeypatch):
    port = _free_port()
    monkeypatch.setattr(socket, "getaddrinfo", _addrinfo((socket.AF_INET6, "::1"), (socket.AF_INET, "127.0.0.1")))

    with pytest.raises(ConnectionRefusedError):
        he.create_connection(("example.test", port), timeout=5)


def test_all_attempts_timing_out_raise_timeout_error(he, monkeypatch):
    monkeypatch.setattr(
        socket, "getaddrinfo", _addrinfo((socket.AF_INET6, "2001:db8::1"), (socket.AF_INET, "192.0.2.1"))
    )
    monkeypatch.setattr(he, "_socket_factory", _factory_blackholing(socket.AF_INET6, socket.AF_INET))

    t = time.monotonic()
    with pytest.raises(TimeoutError):
        he.create_connection(("example.test", 443), timeout=0.4)
    # Each attempt has its own timeout; the last one starts one delay later.
    assert time.monotonic() - t < 0.4 + he.ATTEMPT_DELAY + 0.5


def test_socket_options_and_source_address_are_applied_before_connect(he, listener, monkeypatch):
    start, _ = listener
    port = start([(socket.AF_INET, "127.0.0.1")])
    monkeypatch.setattr(
        socket, "getaddrinfo", _addrinfo((socket.AF_INET6, "2001:db8::1"), (socket.AF_INET, "127.0.0.1"))
    )
    monkeypatch.setattr(he, "_socket_factory", _factory_blackholing(socket.AF_INET6))
    _BlackholeSocket.instances.clear()
    options = [(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)]

    sock = he.create_connection(("example.test", port), 5, ("127.0.0.1", 0), options)
    try:
        assert sock.getsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE) == 1
        assert sock.getsockname()[0] == "127.0.0.1"
        blackhole = _BlackholeSocket.instances[0]
        assert blackhole.options == [options[0]]
        assert blackhole.bound == ("127.0.0.1", 0)
    finally:
        sock.close()


def test_winning_socket_gets_the_requested_timeout(he, listener, monkeypatch):
    start, _ = listener
    port = start([(socket.AF_INET, "127.0.0.1")])
    monkeypatch.setattr(
        socket, "getaddrinfo", _addrinfo((socket.AF_INET6, "2001:db8::1"), (socket.AF_INET, "127.0.0.1"))
    )
    monkeypatch.setattr(he, "_socket_factory", _factory_blackholing(socket.AF_INET6))

    sock = he.create_connection(("example.test", port), timeout=12.5)
    try:
        assert sock.gettimeout() == 12.5
    finally:
        sock.close()


def test_ip_literal_in_brackets_is_resolved_without_brackets(he, monkeypatch):
    seen = []

    def _fake(host, port, *args, **kwargs):
        seen.append(host)
        return [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", (host, port, 0, 0))]

    monkeypatch.setattr(socket, "getaddrinfo", _fake)
    monkeypatch.setattr(he, "_original", lambda *args: "original-socket")
    he.create_connection(("[2001:db8::1]", 443), 5)
    assert seen == ["2001:db8::1"]


# ── installing into urllib3 ──


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):
        pass


def test_install_patches_urllib3_and_requests_uses_it(he, monkeypatch):
    import requests
    import urllib3.util.connection as u3conn

    # Restored at teardown, whatever install() does to it.
    monkeypatch.setattr(u3conn, "create_connection", u3conn.create_connection)
    server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    monkeypatch.setattr(
        socket, "getaddrinfo", _addrinfo((socket.AF_INET6, "2001:db8::1"), (socket.AF_INET, "127.0.0.1"))
    )
    monkeypatch.setattr(he, "_socket_factory", _factory_blackholing(socket.AF_INET6))

    try:
        assert he.install() is True
        assert u3conn.create_connection is he.create_connection
        assert he.install() is True  # idempotent

        t = time.monotonic()
        response = requests.get(f"http://dualstack.test:{port}/", timeout=30)
        assert response.text == "ok"
        assert time.monotonic() - t < 1.0
    finally:
        server.shutdown()
        server.server_close()


def test_install_refuses_when_urllib3_signature_changed(he, monkeypatch):
    import urllib3.util.connection as u3conn

    def _moved(address, *, timeout=None, happy_eyeballs=None):
        raise AssertionError("not called")

    monkeypatch.setattr(u3conn, "create_connection", _moved)
    assert he.install() is False
    assert u3conn.create_connection is _moved


def test_install_without_urllib3_is_a_silent_no_op(he, monkeypatch):
    import builtins

    real_import = builtins.__import__

    def _no_urllib3(name, *args, **kwargs):
        if name.startswith("urllib3"):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_urllib3)
    assert he.install() is False


# ── subprocess environment ──


def test_subprocess_env_prepends_site_dir_to_existing_pythonpath():
    from plugins.builtin.gallery_dl._subprocess_env import SITE_DIR, gdl_subprocess_env

    env = gdl_subprocess_env({"PATH": "/usr/bin", "PYTHONPATH": "/somewhere"}, PYTHONUNBUFFERED="1")
    assert env == {"PATH": "/usr/bin", "PYTHONPATH": f"{SITE_DIR}{os.pathsep}/somewhere", "PYTHONUNBUFFERED": "1"}
    assert gdl_subprocess_env({})["PYTHONPATH"] == str(SITE_DIR)


def test_subprocess_env_defaults_to_the_current_environment(monkeypatch):
    from plugins.builtin.gallery_dl._subprocess_env import SITE_DIR, gdl_subprocess_env

    monkeypatch.setenv("JYZROX_ENV_PROBE", "kept")
    monkeypatch.delenv("PYTHONPATH", raising=False)
    env = gdl_subprocess_env()
    assert env["JYZROX_ENV_PROBE"] == "kept"
    assert env["PYTHONPATH"] == str(SITE_DIR)


def test_site_dir_contains_only_sitecustomize():
    """Everything in the directory becomes a top-level module inside gallery-dl."""
    from plugins.builtin.gallery_dl._subprocess_env import SITE_DIR

    assert SITE_DIR == _SITE_DIR
    assert sorted(p.name for p in SITE_DIR.iterdir() if p.name != "__pycache__") == ["sitecustomize.py"]


def test_real_interpreter_with_subprocess_env_installs_happy_eyeballs():
    """The same mechanism gallery-dl gets: ``site`` imports our sitecustomize at startup."""
    import subprocess
    import sys

    from plugins.builtin.gallery_dl._subprocess_env import gdl_subprocess_env

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sitecustomize, urllib3.util.connection as c; "
            "print(sitecustomize.__file__, sitecustomize.INSTALLED, c.create_connection is sitecustomize.create_connection)",
        ],
        env=gdl_subprocess_env(),
        capture_output=True,
        text=True,
        timeout=30,
        cwd="/",
    )
    assert result.returncode == 0, result.stderr
    path, installed, patched = result.stdout.split()
    assert Path(path) == _SITE_DIR / "sitecustomize.py"
    assert (installed, patched) == ("True", "True")
    assert result.stderr == ""  # gallery-dl's stderr is parsed by Jyzrox
