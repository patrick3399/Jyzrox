"""Regression tests for the keyset-cursor NULL marker.

Bug A: a NULL sort value was encoded as "" and "" was parsed back as NULL, so a
title-sorted page ending on a gallery whose title is the empty string resumed
inside the NULL tail and skipped every later non-NULL title.
Bug B: the image browser cursor on a NULL ``images.added_at`` degraded to an
id-only predicate, skipping/repeating rows (PostgreSQL DESC puts NULLs first).
"""

from datetime import datetime

import pytest
from sqlalchemy import text

from services.gallery_sort import SORT_SPECS, encode_value, parse_cursor_value

_TITLES = [None, "", "a", "b", "b"]


async def _seed_titles(db) -> list[tuple[int, str | None]]:
    rows = []
    for i, t in enumerate(_TITLES):
        await db.execute(
            text(
                "INSERT INTO galleries (source, source_id, title, pages, download_status, tags_array, visibility) "
                "VALUES ('ct', :sid, :t, 1, 'completed', '[]', 'public')"
            ),
            {"sid": f"s{i}", "t": t},
        )
        await db.commit()
        gid = (
            await db.execute(text("SELECT id FROM galleries WHERE source='ct' AND source_id=:s"), {"s": f"s{i}"})
        ).scalar()
        rows.append((gid, t))
    return rows


@pytest.mark.parametrize("direction", ["asc", "desc"])
async def test_search_title_sort_cursor_on_empty_title_does_not_skip_rest(client, db_session, direction):
    rows = await _seed_titles(db_session)
    rev = direction == "desc"
    nonnull = sorted([r for r in rows if r[1] is not None], key=lambda r: (r[1], r[0]), reverse=rev)
    nulls = sorted([r for r in rows if r[1] is None], key=lambda r: r[0], reverse=rev)
    expected = [r[0] for r in nonnull + nulls]

    seen: list[int] = []
    params = {"q": "source:ct", "sort": "title", "dir": direction, "limit": 1}
    for _ in range(20):
        r = await client.get("/api/search/", params=params)
        assert r.status_code == 200, r.text
        data = r.json()
        seen.extend(i["id"] for i in data["items"])
        if not data["has_next"]:
            break
        params = {**params, "cursor": data["next_cursor"]}
    assert seen == expected


def test_encode_value_null_is_json_null_and_legacy_empty_marker_still_parses():
    assert encode_value(None) is None
    assert encode_value("") == ""
    assert parse_cursor_value(SORT_SPECS["title"], None) is None
    assert parse_cursor_value(SORT_SPECS["title"], "") == ""  # real empty title
    for key in ("posted_at", "rating"):  # legacy "" cursors from open tabs
        assert parse_cursor_value(SORT_SPECS[key], "") is None
        assert parse_cursor_value(SORT_SPECS[key], None) is None
    assert parse_cursor_value(SORT_SPECS["posted_at"], encode_value(datetime(2024, 1, 2))) == datetime(2024, 1, 2)


async def test_search_cursor_with_non_string_value_is_400(client, db_session):
    import base64
    import hashlib
    import hmac
    import json

    from routers.search import _cursor_secret

    await _seed_titles(db_session)
    enc = (
        base64.urlsafe_b64encode(json.dumps({"id": 1, "v": 5, "s": "title", "d": "asc"}).encode()).decode().rstrip("=")
    )
    sig = hmac.new(_cursor_secret(), enc.encode(), hashlib.sha256).hexdigest()
    r = await client.get(
        "/api/search/", params={"q": "source:ct", "sort": "title", "dir": "asc", "cursor": f"{enc}.{sig}"}
    )
    assert r.status_code == 400


@pytest.mark.parametrize("sort", ["newest", "oldest"])
async def test_browse_images_cursor_on_null_added_at_visits_all(client, db_session, sort):
    await db_session.execute(
        text(
            "INSERT INTO galleries (source, source_id, title, pages, download_status, tags_array, visibility) "
            "VALUES ('im', 'g', 'G', 1, 'completed', '[]', 'public')"
        )
    )
    gid = (await db_session.execute(text("SELECT id FROM galleries WHERE source='im'"))).scalar()
    stamps = [
        None,
        "2024-05-05 00:00:00.000000",
        None,
        "2024-05-05 00:00:00.000000",
        "2024-09-01 00:00:00.000000",
        None,
    ]
    rows = []
    for n, at in enumerate(stamps, start=1):
        await db_session.execute(
            text(
                "INSERT OR IGNORE INTO blobs (sha256, file_size, extension, width, height) "
                "VALUES (:sha, 1000, 'jpg', 10, 10)"
            ),
            {"sha": f"sha_{n}"},
        )
        await db_session.execute(
            text(
                "INSERT INTO images (gallery_id, page_num, filename, blob_sha256, added_at) "
                "VALUES (:g, :n, :f, :sha, :a)"
            ),
            {"g": gid, "n": n, "f": f"{n}.jpg", "sha": f"sha_{n}", "a": at},
        )
        await db_session.commit()
        iid = (await db_session.execute(text("SELECT id FROM images WHERE page_num=:n"), {"n": n})).scalar()
        rows.append((iid, at))
    rev = sort == "newest"
    dated = sorted([r for r in rows if r[1]], key=lambda r: (r[1], r[0]), reverse=rev)
    nulls = sorted([r for r in rows if not r[1]], key=lambda r: r[0], reverse=rev)
    expected = [r[0] for r in (nulls + dated if rev else dated + nulls)]

    seen: list[int] = []
    params = {"sort": sort, "limit": 1}
    for _ in range(20):
        r = await client.get("/api/library/images", params=params)
        assert r.status_code == 200, r.text
        data = r.json()
        seen.extend(i["id"] for i in data["images"])
        if not data["has_next"]:
            break
        params = {**params, "cursor": data["next_cursor"]}
    assert seen == expected
