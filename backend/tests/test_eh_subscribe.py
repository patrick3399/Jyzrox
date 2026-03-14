"""
Tests for EH subscription functionality.

Covers:
- check_eh_new_works() from plugins.builtin.ehentai._subscribe

EhClient is mocked as an async context manager throughout; no network calls
are made.  Redis and settings are patched so the lazy imports inside
check_eh_new_works() resolve to mocks rather than live services.

Patch targets use the source module paths because the imports happen inside
the function body via `from X import Y`:
  - "core.redis_client.get_redis"   (not the _subscribe module)
  - "services.eh_client.EhClient"   (not the _subscribe module)
  - "core.config.settings"          (not the _subscribe module)
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from plugins.models import NewWork


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_gallery(gid: int, token: str = "abc1234567", posted_at: int = 1700000000) -> dict:
    """Build a minimal gallery dict as returned by EhClient.search()."""
    return {
        "gid": gid,
        "token": token,
        "title": f"Gallery {gid}",
        "thumb": f"https://ehgt.org/thumb/{gid}.jpg",
        "posted_at": posted_at,
    }


def _make_search_result(
    gids: list[int],
    next_gid: int | None = None,
    has_prev: bool = False,
) -> dict:
    """Build a search result dict as returned by EhClient.search()."""
    return {
        "galleries": [_make_gallery(g) for g in gids],
        "total": len(gids),
        "next_gid": next_gid,
        "has_prev": has_prev,
    }


def _make_eh_client_mock(search_side_effect=None, search_return_value=None) -> AsyncMock:
    """Return an async context-manager mock for EhClient.

    Pass either side_effect (list of return values for successive calls) or a
    single return_value.
    """
    mock = AsyncMock()
    if search_side_effect is not None:
        mock.search = AsyncMock(side_effect=search_side_effect)
    else:
        mock.search = AsyncMock(return_value=search_return_value or _make_search_result([]))
    mock.__aenter__ = AsyncMock(return_value=mock)
    mock.__aexit__ = AsyncMock(return_value=None)
    return mock


def _make_mock_redis(use_ex_value: bytes | None = None) -> AsyncMock:
    """Return an AsyncMock Redis where get() returns use_ex_value."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=use_ex_value)
    return redis


# ---------------------------------------------------------------------------
# check_eh_new_works — incremental check, all results are new
# ---------------------------------------------------------------------------


class TestCheckEhNewWorksIncremental:
    """Incremental checks where last_known is set."""

    async def test_incremental_all_new_returns_five_works(self):
        """Galleries with gids all above last_known should all be returned."""
        search_result = _make_search_result([105, 104, 103, 102, 101])
        eh_mock = _make_eh_client_mock(search_return_value=search_result)
        mock_redis = _make_mock_redis()

        with (
            patch("core.redis_client.get_redis", return_value=mock_redis),
            patch("core.config.settings", eh_use_ex=False),
            patch("services.eh_client.EhClient", return_value=eh_mock),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            from plugins.builtin.ehentai._subscribe import check_eh_new_works
            results = await check_eh_new_works(
                query="uploader:Foo",
                last_known="100",
                credentials={"ipb_member_id": "123"},
            )

        assert len(results) == 5
        assert all(isinstance(r, NewWork) for r in results)
        # Newest first
        assert results[0].source_id == "105"
        assert results[-1].source_id == "101"

    async def test_incremental_boundary_stops_at_last_known(self):
        """Galleries with gid <= last_known should be excluded; boundary halts iteration."""
        search_result = _make_search_result([105, 104, 100, 99])
        eh_mock = _make_eh_client_mock(search_return_value=search_result)
        mock_redis = _make_mock_redis()

        with (
            patch("core.redis_client.get_redis", return_value=mock_redis),
            patch("core.config.settings", eh_use_ex=False),
            patch("services.eh_client.EhClient", return_value=eh_mock),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            from plugins.builtin.ehentai._subscribe import check_eh_new_works
            results = await check_eh_new_works(
                query="female:catgirl",
                last_known="100",
                credentials={"ipb_member_id": "123"},
            )

        assert len(results) == 2
        source_ids = [r.source_id for r in results]
        assert "105" in source_ids
        assert "104" in source_ids
        assert "100" not in source_ids
        assert "99" not in source_ids

    async def test_incremental_boundary_exactly_equal_excluded(self):
        """A gallery whose gid equals last_known is treated as already seen (excluded)."""
        search_result = _make_search_result([201, 200])
        eh_mock = _make_eh_client_mock(search_return_value=search_result)
        mock_redis = _make_mock_redis()

        with (
            patch("core.redis_client.get_redis", return_value=mock_redis),
            patch("core.config.settings", eh_use_ex=False),
            patch("services.eh_client.EhClient", return_value=eh_mock),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            from plugins.builtin.ehentai._subscribe import check_eh_new_works
            results = await check_eh_new_works(
                query="artist:test",
                last_known="200",
                credentials=None,
            )

        assert len(results) == 1
        assert results[0].source_id == "201"


# ---------------------------------------------------------------------------
# check_eh_new_works — first check (last_known=None)
# ---------------------------------------------------------------------------


class TestCheckEhNewWorksFirstCheck:
    """Behaviour on the very first check (last_known=None)."""

    async def test_first_check_returns_first_page_only(self):
        """First check must not paginate beyond the first page even if next_gid is present."""
        page1 = _make_search_result([500, 499, 498], next_gid=497)
        eh_mock = _make_eh_client_mock(search_return_value=page1)
        mock_redis = _make_mock_redis()

        with (
            patch("core.redis_client.get_redis", return_value=mock_redis),
            patch("core.config.settings", eh_use_ex=False),
            patch("services.eh_client.EhClient", return_value=eh_mock),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            from plugins.builtin.ehentai._subscribe import check_eh_new_works
            results = await check_eh_new_works(
                query="uploader:Bar",
                last_known=None,
                credentials={"ipb_member_id": "42"},
            )

        assert len(results) == 3
        # search() must be called exactly once — no second page
        eh_mock.search.assert_awaited_once()

    async def test_first_check_empty_results_returns_empty_list(self):
        """First check with no galleries should return an empty list without errors."""
        eh_mock = _make_eh_client_mock(search_return_value=_make_search_result([]))
        mock_redis = _make_mock_redis()

        with (
            patch("core.redis_client.get_redis", return_value=mock_redis),
            patch("core.config.settings", eh_use_ex=False),
            patch("services.eh_client.EhClient", return_value=eh_mock),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            from plugins.builtin.ehentai._subscribe import check_eh_new_works
            results = await check_eh_new_works(
                query="nonexistent query",
                last_known=None,
                credentials={"ipb_member_id": "42"},
            )

        assert results == []


# ---------------------------------------------------------------------------
# check_eh_new_works — edge cases
# ---------------------------------------------------------------------------


class TestCheckEhNewWorksEdgeCases:
    """Empty results, no credentials, multi-page pagination."""

    async def test_empty_galleries_returns_empty_list(self):
        """Mock returning empty galleries list should yield empty results."""
        eh_mock = _make_eh_client_mock(search_return_value=_make_search_result([]))
        mock_redis = _make_mock_redis()

        with (
            patch("core.redis_client.get_redis", return_value=mock_redis),
            patch("core.config.settings", eh_use_ex=False),
            patch("services.eh_client.EhClient", return_value=eh_mock),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            from plugins.builtin.ehentai._subscribe import check_eh_new_works
            results = await check_eh_new_works(
                query="female:catgirl",
                last_known="50",
                credentials={"ipb_member_id": "9"},
            )

        assert results == []

    async def test_no_credentials_returns_empty_list(self):
        """credentials=None means no API access; should return empty list immediately."""
        # EhClient is still constructed (with empty cookies), but search returns empty.
        # The important thing is that the function handles it gracefully.
        eh_mock = _make_eh_client_mock(search_return_value=_make_search_result([]))
        mock_redis = _make_mock_redis()

        with (
            patch("core.redis_client.get_redis", return_value=mock_redis),
            patch("core.config.settings", eh_use_ex=False),
            patch("services.eh_client.EhClient", return_value=eh_mock),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            from plugins.builtin.ehentai._subscribe import check_eh_new_works
            results = await check_eh_new_works(
                query="female:catgirl",
                last_known="50",
                credentials=None,
            )

        assert results == []

    async def test_no_credentials_uses_eh_not_ex(self):
        """With no cookies, use_ex must be forced to False (public EH only)."""
        captured_args: list = []

        def _capture_client(*args, **kwargs):
            captured_args.extend(args)
            mock = AsyncMock()
            mock.search = AsyncMock(return_value=_make_search_result([]))
            mock.__aenter__ = AsyncMock(return_value=mock)
            mock.__aexit__ = AsyncMock(return_value=None)
            return mock

        mock_redis = _make_mock_redis()

        with (
            patch("core.redis_client.get_redis", return_value=mock_redis),
            patch("core.config.settings", eh_use_ex=True),
            patch("services.eh_client.EhClient", side_effect=_capture_client),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            from plugins.builtin.ehentai._subscribe import check_eh_new_works
            await check_eh_new_works(
                query="test",
                last_known=None,
                credentials=None,
            )

        # Second positional arg to EhClient is use_ex; must be False when no cookies
        assert len(captured_args) >= 2
        use_ex_flag = captured_args[1]
        assert use_ex_flag is False

    async def test_multi_page_pagination_fetches_two_pages(self):
        """When last_known is set and first page has no boundary, a second page must be fetched."""
        page1 = _make_search_result([200, 199, 198], next_gid=197)
        page2 = _make_search_result([197, 196, 100, 99])

        eh_mock = _make_eh_client_mock(search_side_effect=[page1, page2])
        mock_redis = _make_mock_redis()

        with (
            patch("core.redis_client.get_redis", return_value=mock_redis),
            patch("core.config.settings", eh_use_ex=False),
            patch("services.eh_client.EhClient", return_value=eh_mock),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            from plugins.builtin.ehentai._subscribe import check_eh_new_works
            results = await check_eh_new_works(
                query="uploader:Multi",
                last_known="100",
                credentials={"ipb_member_id": "7"},
            )

        # Two pages fetched
        assert eh_mock.search.await_count == 2

        # All gids above 100 collected: 200, 199, 198, 197, 196
        source_ids = {r.source_id for r in results}
        assert source_ids == {"200", "199", "198", "197", "196"}

        # Boundary gids not included
        assert "100" not in source_ids
        assert "99" not in source_ids

    async def test_multi_page_second_page_called_with_cursor(self):
        """next_gid from page 1 must be passed as next_gid argument to page 2 search."""
        page1 = _make_search_result([300, 299], next_gid=250)
        page2 = _make_search_result([250, 100])

        eh_mock = _make_eh_client_mock(search_side_effect=[page1, page2])
        mock_redis = _make_mock_redis()

        with (
            patch("core.redis_client.get_redis", return_value=mock_redis),
            patch("core.config.settings", eh_use_ex=False),
            patch("services.eh_client.EhClient", return_value=eh_mock),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            from plugins.builtin.ehentai._subscribe import check_eh_new_works
            await check_eh_new_works(
                query="artist:cursor_test",
                last_known="100",
                credentials={"ipb_member_id": "8"},
            )

        # Second search call must pass next_gid=250
        second_call_kwargs = eh_mock.search.call_args_list[1].kwargs
        assert second_call_kwargs.get("next_gid") == 250

    async def test_eh_client_exception_returns_empty_list(self):
        """Exceptions from EhClient.search() should be caught and return empty list."""
        eh_mock = _make_eh_client_mock()
        eh_mock.search = AsyncMock(side_effect=RuntimeError("connection refused"))
        mock_redis = _make_mock_redis()

        with (
            patch("core.redis_client.get_redis", return_value=mock_redis),
            patch("core.config.settings", eh_use_ex=False),
            patch("services.eh_client.EhClient", return_value=eh_mock),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            from plugins.builtin.ehentai._subscribe import check_eh_new_works
            results = await check_eh_new_works(
                query="test",
                last_known="10",
                credentials={"ipb_member_id": "1"},
            )

        assert results == []

    async def test_redis_use_ex_setting_overrides_config(self):
        """Redis setting:eh_use_ex=b'1' must take precedence over settings.eh_use_ex=False."""
        captured_args: list = []

        def _capture_client(*args, **kwargs):
            captured_args.extend(args)
            mock = AsyncMock()
            mock.search = AsyncMock(return_value=_make_search_result([]))
            mock.__aenter__ = AsyncMock(return_value=mock)
            mock.__aexit__ = AsyncMock(return_value=None)
            return mock

        # Redis says use_ex = True; config says False
        mock_redis = _make_mock_redis(use_ex_value=b"1")

        with (
            patch("core.redis_client.get_redis", return_value=mock_redis),
            patch("core.config.settings", eh_use_ex=False),
            patch("services.eh_client.EhClient", side_effect=_capture_client),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            from plugins.builtin.ehentai._subscribe import check_eh_new_works
            await check_eh_new_works(
                query="test",
                last_known=None,
                credentials={"ipb_member_id": "1", "igneous": "token"},
            )

        assert len(captured_args) >= 2
        use_ex_flag = captured_args[1]
        assert use_ex_flag is True

    async def test_string_credentials_parsed_as_json(self):
        """credentials passed as a JSON string should be decoded into a cookies dict."""
        import json as _json

        eh_mock = _make_eh_client_mock(search_return_value=_make_search_result([999]))
        mock_redis = _make_mock_redis()

        with (
            patch("core.redis_client.get_redis", return_value=mock_redis),
            patch("core.config.settings", eh_use_ex=False),
            patch("services.eh_client.EhClient", return_value=eh_mock),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            from plugins.builtin.ehentai._subscribe import check_eh_new_works
            results = await check_eh_new_works(
                query="test",
                last_known=None,
                credentials=_json.dumps({"ipb_member_id": "55", "ipb_pass_hash": "xx"}),
            )

        assert len(results) == 1
        assert results[0].source_id == "999"

    async def test_malformed_json_credentials_returns_results(self):
        """Malformed JSON string credentials should fallback to empty cookies, not crash."""
        eh_mock = _make_eh_client_mock(search_return_value=_make_search_result([50]))
        mock_redis = _make_mock_redis()

        with (
            patch("core.redis_client.get_redis", return_value=mock_redis),
            patch("core.config.settings", eh_use_ex=False),
            patch("services.eh_client.EhClient", return_value=eh_mock),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            from plugins.builtin.ehentai._subscribe import check_eh_new_works
            results = await check_eh_new_works(
                query="test",
                last_known=None,
                credentials="not-valid-json{{{",
            )

        assert len(results) == 1

    async def test_empty_dict_credentials_uses_anonymous(self):
        """Empty dict credentials should work like None — anonymous access."""
        eh_mock = _make_eh_client_mock(search_return_value=_make_search_result([42]))
        mock_redis = _make_mock_redis()

        with (
            patch("core.redis_client.get_redis", return_value=mock_redis),
            patch("core.config.settings", eh_use_ex=False),
            patch("services.eh_client.EhClient", return_value=eh_mock),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            from plugins.builtin.ehentai._subscribe import check_eh_new_works
            results = await check_eh_new_works(
                query="test",
                last_known=None,
                credentials={},
            )

        assert len(results) == 1

    async def test_newwork_fields_populated_correctly(self):
        """NewWork URL, title, source_id, thumbnail_url and posted_at must be set."""
        from datetime import datetime, timezone

        gid = 12345
        token = "abc1234567"
        posted_ts = 1700000000
        gallery = {
            "gid": gid,
            "token": token,
            "title": "Test Gallery",
            "thumb": "https://ehgt.org/thumb/001.jpg",
            "posted_at": posted_ts,
        }
        search_result = {"galleries": [gallery], "total": 1, "next_gid": None, "has_prev": False}

        eh_mock = _make_eh_client_mock(search_return_value=search_result)
        mock_redis = _make_mock_redis()

        with (
            patch("core.redis_client.get_redis", return_value=mock_redis),
            patch("core.config.settings", eh_use_ex=False),
            patch("services.eh_client.EhClient", return_value=eh_mock),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            from plugins.builtin.ehentai._subscribe import check_eh_new_works
            results = await check_eh_new_works(
                query="test",
                last_known=None,
                credentials={"ipb_member_id": "1"},
            )

        assert len(results) == 1
        work = results[0]
        assert work.url == f"https://e-hentai.org/g/{gid}/{token}/"
        assert work.title == "Test Gallery"
        assert work.source_id == str(gid)
        assert work.thumbnail_url == "https://ehgt.org/thumb/001.jpg"
        expected_dt = datetime.fromtimestamp(posted_ts, tz=timezone.utc)
        assert work.posted_at == expected_dt

