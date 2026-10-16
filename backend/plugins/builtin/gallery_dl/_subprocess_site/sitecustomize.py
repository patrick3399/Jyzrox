"""Happy Eyeballs (RFC 8305) for gallery-dl subprocesses.

Jyzrox puts this directory first on ``PYTHONPATH`` for every gallery-dl it
starts, so Python imports this file at interpreter startup (``site`` imports
``sitecustomize``). It replaces ``urllib3.util.connection.create_connection``,
which requests -- and therefore gallery-dl -- uses for every new connection.

urllib3 tries the resolved addresses one after another and gives each the full
connect timeout. When IPv6 is preferred but black-holed upstream (a route
exists, SYNs go unanswered), every new connection to a dual-stack host waits
``timeout`` per AAAA record before IPv4 is tried: 2 x 30 s for a Cloudflare
host. Here attempts are interleaved by family and started every
``ATTEMPT_DELAY`` seconds, or at once when the previous one fails; the first to
connect wins. Hosts that resolve to a single family go to urllib3 unchanged.

Rules for this file:

* stdlib only, plus the urllib3 that is already installed; it runs under the
  upgradable gallery-dl venv and under the system interpreter of the venv-lock
  launcher;
* never raise and never write to stderr -- Jyzrox parses gallery-dl's stderr
  for progress and errors. When urllib3's interface does not match, nothing is
  patched; ``INSTALLED`` says whether it was, which the worker's startup check
  reads;
* nothing else may live in this directory: every ``.py`` here becomes a
  top-level module gallery-dl can import.
"""

import errno
import os
import selectors
import socket
import time
from itertools import zip_longest

ATTEMPT_DELAY = 0.25  # RFC 8305 "Connection Attempt Delay"

_EXPECTED_PARAMS = ("address", "timeout", "source_address", "socket_options")
_PENDING = {errno.EINPROGRESS, errno.EWOULDBLOCK, errno.EAGAIN, errno.EALREADY}

_original = None  # urllib3's own create_connection, once installed
_socket_factory = socket.socket  # tests swap in sockets that never answer


def _interleave(infos: list) -> list:
    """Alternate address families, starting with the family listed first."""
    first = infos[0][0]
    preferred = [info for info in infos if info[0] == first]
    other = [info for info in infos if info[0] != first]
    return [info for pair in zip_longest(preferred, other) for info in pair if info is not None]


def _timeout_value(timeout):
    """urllib3 passes a sentinel for "use the global default"."""
    if timeout is None or isinstance(timeout, (int, float)):
        return timeout
    return socket.getdefaulttimeout()


def create_connection(address, timeout=None, source_address=None, socket_options=None):
    """Drop-in for ``urllib3.util.connection.create_connection``."""
    host, port = address
    if host.startswith("["):
        host = host.strip("[]")
    try:
        host.encode("idna")
        infos = socket.getaddrinfo(host, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except UnicodeError, OSError:
        infos = None
    if not infos or len({info[0] for info in infos}) < 2:
        # Single family, or let urllib3 raise its own resolution errors.
        return _original(address, timeout, source_address, socket_options)

    connect_timeout = _timeout_value(timeout)
    infos = _interleave(infos)
    selector = selectors.DefaultSelector()
    pending: dict = {}  # socket -> deadline (or None)
    last_error: Exception | None = None
    winner = None
    next_index = 0
    next_start = time.monotonic()
    try:
        while True:
            now = time.monotonic()
            if next_index < len(infos) and (now >= next_start or not pending):
                family, socktype, proto, _, sockaddr = infos[next_index]
                next_index += 1
                next_start = now + ATTEMPT_DELAY
                sock = None
                try:
                    sock = _socket_factory(family, socktype, proto)
                    for option in socket_options or ():
                        sock.setsockopt(*option)
                    if source_address:
                        sock.bind(source_address)
                    sock.setblocking(False)
                    err = sock.connect_ex(sockaddr)
                except OSError as exc:
                    if sock is not None:
                        sock.close()
                    last_error = exc
                    next_start = now
                    continue
                if err == 0:
                    winner = sock
                    break
                if err not in _PENDING:
                    sock.close()
                    last_error = OSError(err, os.strerror(err))
                    next_start = now
                    continue
                deadline = None if connect_timeout is None else now + connect_timeout
                pending[sock] = deadline
                selector.register(sock, selectors.EVENT_WRITE)
                continue

            if not pending:
                raise last_error or OSError("getaddrinfo returns an empty list")

            waits = [deadline - now for deadline in pending.values() if deadline is not None]
            if next_index < len(infos):
                waits.append(next_start - now)
            events = selector.select(max(0.0, min(waits)) if waits else None)

            for key, _ in events:
                sock = key.fileobj
                selector.unregister(sock)
                del pending[sock]
                err = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
                if err == 0:
                    winner = sock
                    break
                sock.close()
                last_error = OSError(err, os.strerror(err))
                next_start = time.monotonic()  # a failure starts the next attempt now
            if winner is not None:
                break

            now = time.monotonic()
            for sock, deadline in list(pending.items()):
                if deadline is not None and now >= deadline:
                    selector.unregister(sock)
                    del pending[sock]
                    sock.close()
                    last_error = TimeoutError("timed out")
    finally:
        # The winner has already left ``pending``; everything still in it lost.
        for sock in pending:
            sock.close()
        selector.close()

    winner.setblocking(True)
    winner.settimeout(connect_timeout)
    return winner


def install() -> bool:
    """Replace urllib3's create_connection; False (and no change) on any mismatch."""
    global _original
    try:
        import inspect

        import urllib3.connection
        import urllib3.util.connection as u3conn

        current = u3conn.create_connection
        if current is create_connection:
            return True
        # urllib3.connection must call it through the module attribute, or
        # replacing the attribute would change nothing.
        if getattr(urllib3.connection, "connection", None) is not u3conn:
            return False
        if tuple(inspect.signature(current).parameters) != _EXPECTED_PARAMS:
            return False
        _original = current
        u3conn.create_connection = create_connection
        return True
    except Exception:
        return False


INSTALLED = install()
