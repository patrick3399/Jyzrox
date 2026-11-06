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


def test_cookie_parser_maps_stored_fanboxsessid_field_to_upper_case_cookie():
    """The credentials form saves the declared `fanboxsessid` field as a JSON
    blob; reading it back must yield the upper-case cookie the API expects."""
    field_name = FanboxSourcePlugin().credential_flows()[0].fields[0].name
    stored = json.dumps({field_name: "session"})

    assert _cookies(stored) == {"FANBOXSESSID": "session"}
    # The dict form (in-process callers) must agree with the stored form.
    assert _cookies({field_name: "session"}) == {"FANBOXSESSID": "session"}


async def test_verify_credential_accepts_the_field_the_flow_declares():
    plugin = FanboxSourcePlugin()
    field_name = plugin.credential_flows()[0].fields[0].name

    assert (await plugin.verify_credential({field_name: "session"})).valid
    assert not (await plugin.verify_credential({})).valid


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


# --- Fanbox API wrapped-body shapes (seen live 2026-11-07) ---------------------
# paginateCreator now returns {"pageUrls": [...]}, listCreator {"posts": [...]}
# and post.info {"post": {...}}.  The bare-list parser silently found nothing,
# so subscriptions were recorded as up_to_date with no boundary.


class _WrappedDiscoveryClient(_DiscoveryClient):
    async def get(self, url, **kwargs):
        if "paginateCreator" in url:
            return _Response(payload={"body": {"pageUrls": ["https://api.fanbox.cc/post.listCreator?page=1"]}})
        return _Response(
            payload={
                "body": {
                    "posts": [
                        {
                            "id": "paid",
                            "title": "Paid",
                            "feeRequired": 500,
                            "publishedDatetime": "2026-11-03T12:08:00+09:00",
                            "cover": {"type": "cover_image", "url": "https://cdn.test/paid-cover.jpeg"},
                        },
                        {
                            "id": "free",
                            "title": "Free",
                            "feeRequired": 0,
                            "publishedDatetime": "2026-11-01T16:05:06+09:00",
                        },
                    ]
                }
            }
        )


class _UnknownShapeDiscoveryClient(_DiscoveryClient):
    async def get(self, url, **kwargs):
        return _Response(payload={"body": {"somethingElse": []}})


@pytest.mark.asyncio
async def test_creator_discovery_reads_wrapped_page_urls_and_posts(monkeypatch):
    monkeypatch.setattr("plugins.builtin.fanbox.source.httpx.AsyncClient", _WrappedDiscoveryClient)
    monkeypatch.setattr("plugins.builtin.fanbox.source.get_typed_download_delay", AsyncMock(return_value=0))
    works, latest_id = await FanboxSourcePlugin().discover_posts(
        "https://www.fanbox.cc/@artist",
        None,
        FanboxDownloadPolicy(content="paid_only"),
        "session",
    )

    assert [work.source_id for work in works] == ["paid"]
    assert works[0].thumbnail_url == "https://cdn.test/paid-cover.jpeg"
    assert latest_id == "paid"


@pytest.mark.asyncio
async def test_creator_discovery_unknown_body_shape_raises_instead_of_reporting_up_to_date(monkeypatch):
    monkeypatch.setattr("plugins.builtin.fanbox.source.httpx.AsyncClient", _UnknownShapeDiscoveryClient)
    monkeypatch.setattr("plugins.builtin.fanbox.source.get_typed_download_delay", AsyncMock(return_value=0))

    with pytest.raises(ValueError, match="pageUrls"):
        await FanboxSourcePlugin().discover_posts(
            "https://www.fanbox.cc/@artist", None, FanboxDownloadPolicy(), "session"
        )


def _post_info_client(post: dict):
    class _PostInfoClient(_Client):
        async def get(self, url, **kwargs):
            if "post.info" in url:
                return _Response(payload={"body": {"post": post}})
            return _Response()

    return _PostInfoClient


@pytest.mark.asyncio
async def test_download_reads_post_from_wrapped_post_info_body(monkeypatch, tmp_path: Path):
    post = {
        "id": "42",
        "title": "Paid post",
        "feeRequired": 500,
        "isRestricted": False,
        "creatorId": "artist",
        "publishedDatetime": "2026-11-03T12:08:00+09:00",
        "coverImageUrl": None,
        "body": {"text": "", "images": [{"originalUrl": "https://cdn.test/42.png"}]},
    }
    monkeypatch.setattr("plugins.builtin.fanbox.source.httpx.AsyncClient", _post_info_client(post))
    monkeypatch.setattr("plugins.builtin.fanbox.source.get_typed_download_delay", AsyncMock(return_value=0))

    result = await FanboxSourcePlugin().download(
        "https://www.fanbox.cc/@artist/posts/42",
        tmp_path,
        options={"fanbox": {"content": "paid_only"}},
    )

    assert (result.status, result.downloaded, result.total) == ("done", 1, 1)
    assert json.loads((tmp_path / "42_p0001.png.json").read_text())["fee_required"] == 500


@pytest.mark.asyncio
async def test_restricted_post_with_null_body_is_skipped_not_saved_as_cover_only(monkeypatch, tmp_path: Path):
    post = {
        "id": "42",
        "title": "Locked",
        "feeRequired": 500,
        "isRestricted": True,
        "creatorId": "artist",
        "coverImageUrl": "https://cdn.test/cover.jpeg",
        "body": None,
    }
    monkeypatch.setattr("plugins.builtin.fanbox.source.httpx.AsyncClient", _post_info_client(post))
    callback = AsyncMock()
    options = {"fanbox": {"content": "accessible"}, "diagnostic_ctx": {}}

    result = await FanboxSourcePlugin().download(
        "https://www.fanbox.cc/@artist/posts/42", tmp_path, on_file=callback, options=options
    )

    assert (result.status, result.downloaded, result.total) == ("done", 0, 0)
    assert options["diagnostic_ctx"]["source_summary"]["skipped_inaccessible"] == 1
    assert not list(tmp_path.iterdir())
    callback.assert_not_awaited()
