"""Regression: nginx must serve `.jxl` blobs as image/jxl.

Incident 2026-11-19 (Weibo JXL, gallery weibo/3944967175): stock mime.types has
no JPEG XL entry, so /media/cas/*.jxl would be sent as application/octet-stream.
"""

import re
from pathlib import Path

import pytest

_TEMPLATE = Path(__file__).resolve().parents[2] / "nginx" / "nginx.conf.template"


@pytest.mark.skipif(not _TEMPLATE.exists(), reason="nginx template is outside this checkout")
def test_nginx_template_maps_jxl_mime_type():
    conf = "\n".join(line.split("#", 1)[0] for line in _TEMPLATE.read_text(encoding="utf-8").splitlines())
    blocks = re.findall(r"^\s*types\s*\{([^}]*)\}", conf, re.M)
    assert any(re.search(r"\bimage/jxl\s+jxl\s*;", b) for b in blocks), "no `types` block maps image/jxl to jxl"
