"""Container log volume configuration (ADR 0031)."""

import re
import shlex
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[2]
_COMPOSE = _ROOT / "docker-compose.yml"
_NGINX = _ROOT / "nginx" / "nginx.conf.template"


def _compose() -> dict:
    return yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))


def _nginx_conf() -> str:
    text = _NGINX.read_text(encoding="utf-8")
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


def test_compose_default_logging_uses_compressed_local_driver():
    cfg = _compose()["x-logging"]
    assert cfg["driver"] == "local"
    assert cfg["options"] == {"max-size": "20m", "max-file": "5"}


def test_every_compose_service_uses_the_shared_logging_config():
    data = _compose()
    missing = [name for name, svc in data["services"].items() if svc.get("logging") != data["x-logging"]]
    assert missing == []


def test_postgres_does_not_log_every_health_check_connection():
    cmd = _compose()["services"]["postgres"]["command"]
    assert "log_connections=on" not in cmd
    assert "log_disconnections=on" not in cmd
    assert "log_min_duration_statement=1000" in cmd


def test_api_uvicorn_runs_without_access_log():
    assert "--no-access-log" in _compose()["services"]["api"]["command"]


def test_imgproxy_logs_warnings_only_without_ansi_colors():
    env = _compose()["services"]["imgproxy"]["environment"]
    assert env["IMGPROXY_LOG_LEVEL"] == "${IMGPROXY_LOG_LEVEL:-warn}"
    assert env["IMGPROXY_LOG_FORMAT"] == "structured"


def test_nginx_read_logging_is_an_operator_toggle_defaulting_off():
    env = _compose()["services"]["nginx"]["environment"]
    assert "NGINX_ACCESS_LOG_READS=${NGINX_ACCESS_LOG_READS:-0}" in env


@pytest.mark.skipif(not _NGINX.exists(), reason="nginx template is outside this checkout")
def test_nginx_access_log_keeps_only_writes_errors_and_slow_requests():
    conf = _nginx_conf()
    assert re.search(r"map\s+\$request_method\s+\$jyzrox_write\s*\{[^}]*\bGET\s+0;[^}]*\bHEAD\s+0;", conf, re.S)
    assert re.search(r"map\s+\$status\s+\$jyzrox_error\s*\{[^}]*~\^\[45\]\s+1;", conf, re.S)
    assert re.search(r"map\s+\$request_time\s+\$jyzrox_slow\s*\{[^}]*~\^0\\\.\s+0;", conf, re.S)
    assert re.search(r"000\s+\$\{NGINX_ACCESS_LOG_READS\};", conf)
    assert re.search(r"access_log\s+/var/log/nginx/access\.log\s+jyzrox\s+if=\$jyzrox_loggable\s*;", conf)
    assert "rid=$upstream_http_x_request_id" in conf


_DOCKERFILE = _ROOT / "nginx" / "Dockerfile"


def _envsubst_filter() -> str:
    text = _DOCKERFILE.read_text(encoding="utf-8")
    match = re.search(r"^ENV NGINX_ENVSUBST_FILTER=(\S+)\s*$", text, re.M)
    assert match, "nginx/Dockerfile must set NGINX_ENVSUBST_FILTER"
    return match.group(1)


@pytest.mark.parametrize(
    ("pattern", "name", "expected"),
    [
        ("NGINX_CLIENT_MAX_BODY_SIZE", "NGINX_ACCESS_LOG_READS", False),  # pre-change value
        ("NGINX_CLIENT_MAX_BODY_SIZE", "NGINX_CLIENT_MAX_BODY_SIZE", True),
    ],
)
def test_envsubst_filter_matching_semantics(pattern, name, expected):
    assert bool(re.fullmatch(pattern, name)) is expected


def test_nginx_envsubst_filter_includes_access_log_toggle():
    """Without it nginx fails with `unknown "nginx_access_log_reads" variable`."""
    pattern = _envsubst_filter()
    assert re.fullmatch(pattern, "NGINX_CLIENT_MAX_BODY_SIZE")
    assert re.fullmatch(pattern, "NGINX_ACCESS_LOG_READS")
    assert re.search(r"^ENV NGINX_ACCESS_LOG_READS=0\s*$", _DOCKERFILE.read_text(encoding="utf-8"), re.M)


def test_postgres_command_has_no_inline_comment_tokens():
    """`command: >` is a folded scalar: a `#` line inside it becomes argv tokens."""
    tokens = shlex.split(_compose()["services"]["postgres"]["command"])
    bad = [t for t in tokens if t not in ("postgres", "-c") and not re.fullmatch(r"[a-z_]+=\S+", t)]
    assert bad == []


def test_no_compose_command_contains_a_folded_comment():
    offenders = []
    for name, svc in _compose()["services"].items():
        cmd = svc.get("command")
        if isinstance(cmd, str) and any(t.startswith("#") for t in shlex.split(cmd)):
            offenders.append(name)
    assert offenders == []
