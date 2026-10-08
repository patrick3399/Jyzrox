"""URL-determined gallery identity for gallery-dl downloads (ADR 0016)."""

import pytest

from plugins.builtin.gallery_dl import _identity
from plugins.builtin.gallery_dl._identity import UrlIdentity, resolve_url_identity
from plugins.builtin.gallery_dl._metadata import _extract_artist

# (url, what gallery_dl.extractor.find() yields for it on 1.32.15)
_MATCHES = {
    "https://x.com/someuser/media": ("twitter", "media", ("someuser",)),
    "https://x.com/someuser": ("twitter", "user", ("someuser", None)),
    "https://x.com/someuser/status/123": ("twitter", "tweet", ("someuser", "123")),
    "https://x.com/search?q=cat": ("twitter", "search", ("cat",)),
    "https://x.com/hashtag/cosplay": ("twitter", "hashtag", ("cosplay",)),
    "https://www.instagram.com/someuser/": ("instagram", "user", ("someuser",)),
    "https://www.instagram.com/p/Cabc/": ("instagram", "post", (None, None, None, "Cabc")),
    "https://www.instagram.com/reel/Cabc/": ("instagram", "reel", (None, None, "", "Cabc")),
    "https://www.facebook.com/somepage/photos": ("facebook", "photos", ("somepage",)),
    "https://www.facebook.com/somepage": ("facebook", "user", ("somepage",)),
    "https://www.facebook.com/photo/?fbid=9": ("facebook", "photo", ("9",)),
    "https://weibo.com/u/3802725779?tabtype=album": ("weibo", "album", ("u", "3802725779", None)),
    "https://weibo.com/3802725779": ("weibo", "user", (None, "3802725779")),
    "https://weibo.com/detail/49": ("weibo", "status", ("detail", "49")),
    "https://danbooru.donmai.us/posts?tags=a+b": ("danbooru", "tag", (None, "", None, None, None, "a+b")),
    "https://gelbooru.com/index.php?page=post&s=list&tags=x": ("gelbooru", "tag", ("x",)),
    "https://gelbooru.com/index.php?page=post&s=list&tags=y": ("gelbooru", "tag", ("y",)),
    "https://nhentai.net/g/123456/": ("nhentai", "gallery", ("123456",)),
    "https://x.com/home": ("twitter", "home", ()),
    "https://somesite.example/thing": ("somesite", "thing", ("abc",)),
}


@pytest.fixture(autouse=True)
def _fake_gallery_dl(monkeypatch):
    monkeypatch.setattr(_identity, "_match_url", lambda url: _MATCHES.get(url))


@pytest.mark.parametrize(
    ("url", "source", "source_id"),
    [
        ("https://x.com/someuser/media", "twitter", "someuser"),
        ("https://x.com/someuser", "twitter", "someuser"),
        ("https://www.instagram.com/someuser/", "instagram", "someuser"),
        ("https://www.facebook.com/somepage/photos", "facebook", "somepage"),
        ("https://www.facebook.com/somepage", "facebook", "somepage"),
        ("https://weibo.com/u/3802725779?tabtype=album", "weibo", "3802725779"),
        ("https://weibo.com/3802725779", "weibo", "3802725779"),
    ],
)
def test_account_view_urls_resolve_to_the_bare_account_existing_galleries_use(url, source, source_id):
    assert resolve_url_identity(url) == UrlIdentity(source, source_id, True, source)


@pytest.mark.parametrize(
    ("url", "source_id"),
    [
        ("https://x.com/someuser/status/123", "tweet=someuser/123"),
        ("https://www.instagram.com/p/Cabc/", "post=Cabc"),
        ("https://www.instagram.com/reel/Cabc/", "reel=Cabc"),
        ("https://www.facebook.com/photo/?fbid=9", "photo=9"),
        ("https://weibo.com/detail/49", "status=detail/49"),
    ],
)
def test_single_post_url_is_its_own_gallery_not_the_account(url, source_id):
    identity = resolve_url_identity(url)
    assert identity.source_id == source_id
    assert identity.is_account is False


def test_route_segment_is_never_the_identity_for_query_string_urls():
    """gelbooru/index.php used to swallow every tag search into one gallery."""
    x = resolve_url_identity("https://gelbooru.com/index.php?page=post&s=list&tags=x")
    y = resolve_url_identity("https://gelbooru.com/index.php?page=post&s=list&tags=y")
    assert (x.source, x.source_id) == ("gelbooru", "tag=x")
    assert y.source_id == "tag=y"


def test_distinct_searches_on_one_site_do_not_share_a_gallery():
    assert resolve_url_identity("https://x.com/search?q=cat").source_id == "search=cat"
    assert resolve_url_identity("https://x.com/hashtag/cosplay").source_id == "hashtag=cosplay"
    assert resolve_url_identity("https://danbooru.donmai.us/posts?tags=a+b").source_id == "tag=a+b"


def test_extractor_without_groups_uses_the_subcategory_alone():
    assert resolve_url_identity("https://x.com/home").source_id == "home"


def test_site_missing_from_the_registry_keeps_its_gallery_dl_category_as_source():
    identity = resolve_url_identity("https://somesite.example/thing")
    assert (identity.source, identity.source_id) == ("somesite", "thing=abc")


def test_url_gallery_dl_cannot_parse_returns_none_for_the_legacy_fallback():
    assert resolve_url_identity("https://unknown.example/whatever") is None


def test_overlong_identity_is_truncated_with_a_digest_so_it_stays_unique(monkeypatch):
    long_a = "a" * 300
    long_b = "a" * 299 + "b"
    monkeypatch.setattr(_identity, "_match_url", lambda url: ("twitter", "search", (url,)))
    first = resolve_url_identity(long_a).source_id
    second = resolve_url_identity(long_b).source_id
    assert len(first) <= 120
    assert first != second


@pytest.mark.parametrize(
    ("source", "meta", "expected"),
    [
        ("twitter", {"author": {"name": "cafu0425"}, "user": {"name": "retweeter"}}, "twitter:cafu0425"),
        ("twitter", {"user": {"id": 1, "name": "cafu0425"}}, "twitter:cafu0425"),
        ("instagram", {"username": "enakorin", "fullname": "Enako"}, "instagram:enakorin"),
        ("weibo", {"user": {"idstr": "3802725779", "screen_name": "x"}}, "weibo:3802725779"),
        ("facebook", {"username": "小律 Ritsu", "user_id": "100043885221503"}, "facebook:100043885221503"),
    ],
)
def test_artist_comes_from_the_account_field_so_single_posts_join_the_account(source, meta, expected):
    """ADR 0016: artist_fields beat artist_from (facebook user_id, weibo user.idstr)."""
    assert _extract_artist(source, meta, []) == expected


def test_artist_is_none_when_metadata_carries_no_account_field():
    """weibo album items have no user info; a wrong artist is worse than none."""
    assert _extract_artist("weibo", {"filename": "x", "num": 1}, []) is None


def test_generated_identity_has_no_colon_because_windows_smb_clients_reject_it():
    assert ":" not in resolve_url_identity("https://x.com/someuser/status/123").source_id
