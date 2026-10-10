"""Switching the active account drops cached responses tied to the previous one."""

import fnmatch
from unittest.mock import patch

from redis.exceptions import RedisError

from services.cache import purge_account_scoped_cache


class _FakeRedis:
    def __init__(self, keys: set[str], fail: bool = False):
        self.keys = set(keys)
        self.fail = fail

    async def scan_iter(self, match=None, count=None):
        if self.fail:
            raise RedisError("down")
        for key in sorted(self.keys):
            if fnmatch.fnmatch(key, match):
                yield key

    async def unlink(self, key):
        self.keys.discard(key)
        return 1


async def test_purge_account_scoped_cache_removes_only_account_dependent_eh_keys():
    redis = _FakeRedis({"eh:favorites:0:::", "eh:search:q:::", "eh:gallery:1", "pixiv:illust:1"})

    with patch("services.cache.get_redis", return_value=redis):
        removed = await purge_account_scoped_cache("ehentai")

    assert removed == 2
    assert redis.keys == {"eh:gallery:1", "pixiv:illust:1"}


async def test_purge_account_scoped_cache_removes_pixiv_personal_feeds_but_not_public_search():
    redis = _FakeRedis(
        {
            "pixiv:search:my_bookmarks:public:0",
            "pixiv:search:my_following:public:0",
            "pixiv:search:following_feed:public:0",
            "pixiv:search:public:cat:date_desc",
            "pixiv:illust:1",
        }
    )

    with patch("services.cache.get_redis", return_value=redis):
        removed = await purge_account_scoped_cache("pixiv")

    assert removed == 3
    assert redis.keys == {"pixiv:search:public:cat:date_desc", "pixiv:illust:1"}


async def test_purge_account_scoped_cache_unknown_source_touches_nothing():
    redis = _FakeRedis({"eh:favorites:0:::"})

    with patch("services.cache.get_redis", return_value=redis):
        assert await purge_account_scoped_cache("twitter") == 0

    assert redis.keys == {"eh:favorites:0:::"}


async def test_purge_account_scoped_cache_does_not_raise_when_redis_is_down():
    with patch("services.cache.get_redis", return_value=_FakeRedis({"eh:favorites:0:::"}, fail=True)):
        assert await purge_account_scoped_cache("ehentai") == 0
