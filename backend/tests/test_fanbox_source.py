"""Regression coverage for native Fanbox policy selection and downloads."""

import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from plugins.builtin.fanbox.policy import FanboxDownloadPolicy, fanbox_policy_from_options
from plugins.builtin.fanbox.source import FanboxSourcePlugin, _cookies, _media_urls


def test_policy_keeps_credential_scope_separate_from_selection():
    assert FanboxDownloadPolicy(content="free_only").includes_fee(0)
    assert not FanboxDownloadPolicy(content="free_only").includes_fee(500)
    assert FanboxDownloadPolicy(content="paid_only").includes_fee(500)
    assert not FanboxDownloadPolicy(content="paid_only").includes_fee(0)
    assert FanboxDownloadPolicy(content="price_range", fee_min=300, fee_max=500).includes_fee(500)
    assert not FanboxDownloadPolicy(content="price_range", fee_min=300, fee_max=500).includes_fee(600)


def test_price_range_requires_a_bound():
    with pytest.raises(ValueError, match="price_range"):
        fanbox_policy_from_options({"fanbox": {"content": "price_range"}})


def test_cookie_parser_accepts_stored_fragment_and_plain_session():
    assert _cookies('{"cookies": {"FANBOXSESSID": "session"}}') == {"FANBOXSESSID": "session"}
    assert _cookies("session") == {"FANBOXSESSID": "session"}


def test_media_selection_honors_media_policy():
    post = {
        "coverImageUrl": "https://cdn.test/cover.jpg",
        "body": {
            "images": [{"originalUrl": "https://cdn.test/image.png"}],
            "files": [
                {"url": "https://cdn.test/movie.mp4"},
                {"url": "https://cdn.test/source.zip"},
            ],
        },
    }
    assert _media_urls(post, FanboxDownloadPolicy()) == [
        "https://cdn.test/cover.jpg",
        "https://cdn.test/image.png",
        "https://cdn.test/movie.mp4",
    ]
    assert _media_urls(post, FanboxDownloadPolicy(include_videos=False, include_files=True)) == [
        "https://cdn.test/cover.jpg",
        "https://cdn.test/image.png",
        "https://cdn.test/source.zip",
    ]


class _Response:
    def __init__(self, status_code=200, payload=None, content=b"image", headers=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.content = content
        self.headers = headers or {"content-type": "image/jpeg"}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://api.fanbox.cc/post.info")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("bad status", request=request, response=response)


class _Client:
    def __init__(self, *args, **kwargs):
        self.posts = kwargs.pop("posts") if "posts" in kwargs else None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get(self, url, **kwargs):
        if "post.info" in url:
            return _Response(
                payload={
                    "body": {
                        "id": "42",
                        "title": "Paid post",
                        "feeRequired": 500,
                        "creatorId": "artist",
                        "publishedDatetime": "2026-07-11T00:00:00+00:00",
                        "body": {"images": [{"originalUrl": "https://cdn.test/42.jpg"}]},
                    }
                }
            )
        return _Response()


class _DiscoveryClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get(self, url, **kwargs):
        if "paginateCreator" in url:
            return _Response(payload={"body": ["https://api.fanbox.cc/page/1"]})
        return _Response(
            payload={
                "body": [
                    {"id": "paid", "title": "Paid", "feeRequired": 500, "publishedDatetime": "2026-07-11T00:00:00Z"},
                    {"id": "free", "title": "Free", "feeRequired": 0, "publishedDatetime": "2026-07-10T00:00:00Z"},
                ]
            }
        )


@pytest.mark.asyncio
async def test_paid_post_is_filtered_before_media_request(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("plugins.builtin.fanbox.source.httpx.AsyncClient", _Client)
    plugin = FanboxSourcePlugin()
    callback = AsyncMock()
    options = {"fanbox": {"content": "free_only"}, "diagnostic_ctx": {}}

    result = await plugin.download(
        "https://www.fanbox.cc/@artist/posts/42",
        tmp_path,
        on_file=callback,
        options=options,
    )

    assert result.status == "done"
    assert result.downloaded == 0
    assert options["diagnostic_ctx"]["source_summary"]["skipped_policy"] == 1
    callback.assert_not_awaited()


@pytest.mark.asyncio
async def test_accessible_post_writes_import_metadata(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("plugins.builtin.fanbox.source.httpx.AsyncClient", _Client)
    plugin = FanboxSourcePlugin()
    callback = AsyncMock()

    result = await plugin.download(
        "https://artist.fanbox.cc/posts/42",
        tmp_path,
        on_file=callback,
        options={"fanbox": {"content": "accessible"}},
    )

    assert result.downloaded == 1
    media = tmp_path / "42_p0001.jpg"
    assert media.read_bytes() == b"image"
    assert json.loads((tmp_path / "42_p0001.jpg.json").read_text())["fee_required"] == 500
    callback.assert_awaited_once_with(media, None)


@pytest.mark.asyncio
async def test_creator_discovery_applies_policy_but_advances_all_post_boundary(monkeypatch):
    monkeypatch.setattr("plugins.builtin.fanbox.source.httpx.AsyncClient", _DiscoveryClient)
    monkeypatch.setattr("plugins.builtin.fanbox.source.get_typed_download_delay", AsyncMock(return_value=0))
    works, latest_id = await FanboxSourcePlugin().discover_posts(
        "https://www.fanbox.cc/@artist",
        None,
        FanboxDownloadPolicy(content="free_only"),
        None,
    )

    assert [work.source_id for work in works] == ["free"]
    assert latest_id == "paid"
