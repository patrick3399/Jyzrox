"""Startup self-check of outbound IPv6 and of Happy Eyeballs in the gallery-dl venv.

A black-holed IPv6 upstream (route present, SYNs unanswered) does not fail
anything: downloads still finish, only slower. Without Happy Eyeballs each new
connection to a dual-stack host waits the full connect timeout per AAAA record;
with it, about ``ATTEMPT_DELAY``. Both conditions are silent, so the worker
logs them once at startup:

* IPv6 has a route but no well-known endpoint answers -> warning;
* the gallery-dl venv's interpreter did not install the patch (urllib3's
  interface changed after a venv upgrade, or ``PYTHONPATH`` is not honoured)
  -> warning.

IPv4-only deployments (the tracked compose file) have no IPv6 route and stay
quiet. Nothing here may raise into startup.
"""

import asyncio
import contextlib
import logging
import socket
from pathlib import Path

from plugins.builtin.gallery_dl._subprocess_env import gdl_subprocess_env
from worker.gallery_dl_venv import VENV_ACTIVE

logger = logging.getLogger(__name__)

# Anycast resolvers that also serve DNS-over-HTTPS on 443 (Google, Cloudflare).
IPV6_ENDPOINTS = (("2001:4860:4860::8888", 443), ("2606:4700:4700::1111", 443))
CONNECT_TIMEOUT = 5.0
GDL_PYTHON = VENV_ACTIVE / "bin" / "python"
INACTIVE_EXIT_CODE = 3
_GDL_CHECK_CODE = f"import sitecustomize, sys; sys.exit(0 if sitecustomize.INSTALLED else {INACTIVE_EXIT_CODE})"
_GDL_CHECK_TIMEOUT = 30.0


def _has_ipv6_route() -> bool:
    """Whether the kernel has a route to global IPv6; a UDP connect sends nothing."""
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_DGRAM) as sock:
            sock.connect(IPV6_ENDPOINTS[0])
        return True
    except OSError:
        return False


async def _reachable(host: str, port: int) -> bool:
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), CONNECT_TIMEOUT)
    except OSError, TimeoutError:
        return False
    writer.close()
    with contextlib.suppress(Exception):
        await writer.wait_closed()
    return True


async def check_ipv6_egress() -> str:
    """Return ``"no_route"``, ``"ok"`` or ``"unreachable"``."""
    if not await asyncio.to_thread(_has_ipv6_route):
        return "no_route"
    results = await asyncio.gather(*(_reachable(host, port) for host, port in IPV6_ENDPOINTS))
    return "ok" if any(results) else "unreachable"


async def check_gdl_happy_eyeballs(python: str) -> bool | None:
    """Run ``python`` the way gallery-dl is run and report whether the patch is active.

    ``None`` when the interpreter could not be run or failed for another reason.
    """
    if not Path(python).exists():
        logger.debug("[egress] %s not found; Happy Eyeballs check skipped", python)
        return None
    try:
        proc = await asyncio.create_subprocess_exec(
            python,
            "-c",
            _GDL_CHECK_CODE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
            env=gdl_subprocess_env(),
            cwd="/",
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), _GDL_CHECK_TIMEOUT)
    except (OSError, TimeoutError) as exc:
        logger.warning("[egress] could not run %s to check Happy Eyeballs: %s", python, exc)
        return None
    if proc.returncode == 0:
        return True
    if proc.returncode == INACTIVE_EXIT_CODE:
        return False
    tail = stderr.decode(errors="replace").strip().splitlines()[-1:] or [f"exit {proc.returncode}"]
    logger.warning("[egress] Happy Eyeballs check in %s failed: %s", python, tail[0])
    return None


async def run_startup_checks() -> None:
    """Log the egress state once; never raises."""
    try:
        state = await check_ipv6_egress()
        if state == "unreachable":
            logger.warning(
                "[egress] IPv6 has a route but %s are unreachable: the upstream IPv6 is down or black-holed. "
                "Dual-stack sites fall back to IPv4 (Happy Eyeballs), so sites routed over IPv6 for speed "
                "are slow until it recovers",
                ", ".join(host for host, _ in IPV6_ENDPOINTS),
            )
        elif state == "ok":
            logger.info("[egress] IPv6 egress OK")
        else:
            logger.debug("[egress] no IPv6 route; IPv4 only")

        active = await check_gdl_happy_eyeballs(str(GDL_PYTHON))
        if active is False:
            logger.warning(
                "[egress] Happy Eyeballs is not active in the gallery-dl venv (urllib3 interface changed?): "
                "while IPv6 is black-holed, every new connection to a dual-stack site waits the full "
                "connect timeout per IPv6 address"
            )
        elif active:
            logger.info("[egress] Happy Eyeballs active in the gallery-dl venv")
    except Exception as exc:
        logger.warning("[egress] startup egress check failed: %s", exc)
