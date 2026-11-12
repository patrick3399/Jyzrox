"""Regression tests for F6/BR-006 — authorization of path-addressed media URIs.

Covers `services.media_authz.authorize_media_uri` directly (unit-style, DB +
Redis mocked) and the `/api/auth/check` router integration that consumes it
(audit #67/#68).
"""

import base64
import json
from unittest.mock import patch

from sqlalchemy import text

from services.media_authz import authorize_media_uri

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _insert_blob(db_session, sha256: str, external_path: str) -> None:
    await db_session.execute(
        text(
            "INSERT INTO blobs (sha256, file_size, extension, storage, external_path, ref_count) "
            "VALUES (:sha, 100, 'jpg', 'external', :ext_path, 1)"
        ),
        {"sha": sha256, "ext_path": external_path},
    )
    await db_session.execute(
        text("INSERT INTO blob_locations (blob_sha256, external_path) VALUES (:sha, :ext_path)"),
        {"sha": sha256, "ext_path": external_path},
    )
    await db_session.commit()


async def _insert_gallery_with_image(
    db_session, *, source_id: str, blob_sha256: str, created_by_user_id: int | None, visibility: str
) -> int:
    await db_session.execute(
        text(
            "INSERT INTO galleries (source, source_id, title, download_status, visibility, created_by_user_id) "
            "VALUES ('test', :sid, 'ACL Test', 'downloaded', :vis, :uid)"
        ),
        {"sid": source_id, "vis": visibility, "uid": created_by_user_id},
    )
    await db_session.commit()
    gid = (
        await db_session.execute(text("SELECT id FROM galleries WHERE source_id = :sid"), {"sid": source_id})
    ).scalar_one()
    await db_session.execute(
        text(
            "INSERT INTO images (gallery_id, page_num, blob_sha256, external_path) "
            "SELECT :gid, 1, sha256, external_path FROM blobs WHERE sha256 = :sha"
        ),
        {"gid": gid, "sha": blob_sha256},
    )
    await db_session.commit()
    return gid


def _b64_source(source: str) -> str:
    return base64.urlsafe_b64encode(source.encode()).decode().rstrip("=")


# ---------------------------------------------------------------------------
# /media/libraries/ — gallery ACL enforcement
# ---------------------------------------------------------------------------


async def test_media_authz_libraries_path_of_other_users_private_gallery_denied(
    db_session, db_session_factory, mock_redis
):
    """A user who neither owns nor has a permission row on a private gallery is denied."""
    await _insert_blob(db_session, "sha_other_private", "/mnt/otheruser/page1.jpg")
    await _insert_gallery_with_image(
        db_session,
        source_id="g_other_private",
        blob_sha256="sha_other_private",
        created_by_user_id=1,
        visibility="private",
    )

    with (
        patch("services.media_authz.async_session", db_session_factory),
    ):
        allowed = await authorize_media_uri({"user_id": 2, "role": "member"}, "/media/libraries/otheruser/page1.jpg")
    assert allowed is False


async def test_media_authz_libraries_path_of_own_gallery_allowed(db_session, db_session_factory, mock_redis):
    """The gallery's owner is allowed to fetch its library-path media."""
    await _insert_blob(db_session, "sha_own_private", "/mnt/mine/page1.jpg")
    await _insert_gallery_with_image(
        db_session,
        source_id="g_own_private",
        blob_sha256="sha_own_private",
        created_by_user_id=1,
        visibility="private",
    )

    with (
        patch("services.media_authz.async_session", db_session_factory),
    ):
        allowed = await authorize_media_uri({"user_id": 1, "role": "member"}, "/media/libraries/mine/page1.jpg")
    assert allowed is True


async def test_media_authz_unregistered_mnt_path_denied(db_session, db_session_factory, mock_redis):
    """A /mnt path with no matching blob at all is denied (closes #68 full-tree browsing)."""
    with (
        patch("services.media_authz.async_session", db_session_factory),
    ):
        allowed = await authorize_media_uri(
            {"user_id": 2, "role": "member"}, "/media/libraries/never/registered/anywhere.jpg"
        )
    assert allowed is False


async def test_media_authz_path_traversal_rejected(db_session, db_session_factory, mock_redis):
    """A '..' path segment is rejected outright, without ever touching the DB."""
    with (
        patch("services.media_authz.async_session", db_session_factory),
    ):
        allowed = await authorize_media_uri({"user_id": 2, "role": "member"}, "/media/libraries/../../etc/passwd")
    assert allowed is False


# ---------------------------------------------------------------------------
# /media/image/ — imgproxy source prefix enforcement
# ---------------------------------------------------------------------------


async def test_media_authz_imgproxy_source_outside_cas_thumbs_denied(mock_redis):
    """An imgproxy source outside local:///cas/ or local:///thumbs/ is denied (closes #67)."""
    b64 = _b64_source("local:///backups/x.png")
    uri = f"/media/image/insecure/rs:fill:200:200/{b64}.webp"
    allowed = await authorize_media_uri({"user_id": 2, "role": "member"}, uri)
    assert allowed is False


async def test_media_authz_imgproxy_cas_source_allowed_without_gallery_lookup():
    """A CAS-backed imgproxy source is an authenticated capability."""
    b64 = _b64_source("local:///cas/ab/cd/cdef1234.jpg")
    uri = f"/media/image/insecure/rs:fill:200:200/{b64}.webp"
    allowed = await authorize_media_uri({"user_id": 2, "role": "member"}, uri)
    assert allowed is True


_THUMB_SRC = "thumbs/e5/8e/e58e3a5cc1e7a21c33407335cbe5d11c92a6cdd10e4c5882f250724106fda156/thumb_720.webp"
_CAS_SRC = "cas/16/14/161421bf1d2126806e4644114713c00fa0d68639d644ea4a6e563dc958fa4038.jpg"


async def test_media_authz_imgproxy_dotdot_source_escaping_cas_denied():
    """imgproxy resolves '..' in local:// sources, so a cas/-prefixed source with a
    '..' segment escapes CAS. The prefix check alone accepted it (returned 200
    for local:///cas/../thumbs/... and any other image under /data)."""
    for source in (
        f"local:///cas/../{_THUMB_SRC}",
        "local:///cas/../library/ehentai/a.jpg",
        "local:///thumbs/../../data/backups/x.png",
        "local:///cas/./16/14/x.jpg",
    ):
        uri = f"/media/image/insecure/rs:fit:320:0:0/{_b64_source(source)}.webp"
        assert await authorize_media_uri({"user_id": 2, "role": "member"}, uri) is False, source


async def test_media_authz_imgproxy_split_base64_source_validated_as_joined():
    """imgproxy joins every source segment before base64-decoding. A source
    whose last segment alone decodes to a cas/ path but whose joined form
    points elsewhere must be judged by the joined form."""
    prefix = "local:///backups/xxx/"  # 21 bytes -> 28 base64 chars, keeps the split aligned
    assert len(prefix) % 3 == 0
    whole = _b64_source(prefix + "local:///" + _CAS_SRC)
    head, tail = whole[:28], whole[28:]
    assert base64.urlsafe_b64decode(tail + "=" * (-len(tail) % 4)).decode().startswith("local:///cas/")
    uri = f"/media/image/insecure/rs:fit:320:0:0/{head}/{tail}.webp"
    assert await authorize_media_uri({"user_id": 2, "role": "member"}, uri) is False


async def test_media_authz_imgproxy_plain_source_form_denied():
    """The app only emits base64 sources. A plain/ source is resolved by
    imgproxy from the plain path, not from the base64-looking last segment."""
    uri = f"/media/image/insecure/rs:fit:320:0:0/plain/local:///backups/x/{_b64_source('local:///' + _CAS_SRC)}.webp"
    assert await authorize_media_uri({"user_id": 2, "role": "member"}, uri) is False


async def test_media_authz_imgproxy_request_dot_segments_normalized_like_nginx():
    """nginx resolves dot segments and %2F before proxying to imgproxy but
    forwards the raw $request_uri to auth; the check must see nginx's view."""
    bad = _b64_source("local:///backups/xxx/")
    good = _b64_source("local:///" + _CAS_SRC)
    for uri in (
        f"/media/image/insecure/rs:fit:320:0:0/{bad}/x/../{good}.webp",
        f"/media/image/insecure/rs:fit:320:0:0/{bad}%2F{good}.webp",
        f"/media/image/insecure/rs:fit:320:0:0/{bad}/x/%2e%2e/{good}.webp",
    ):
        assert await authorize_media_uri({"user_id": 2, "role": "member"}, uri) is False, uri


async def test_media_authz_imgproxy_legitimate_source_shapes_allowed():
    """Shapes the PWA (AppImage.tsx) or imgproxy itself legitimately accept stay allowed."""
    cas = _b64_source("local:///" + _CAS_SRC)
    thumb = _b64_source("local:///" + _THUMB_SRC)
    for uri in (
        f"/media/image/insecure/rs:fit:320:0:0/{cas}.avif",
        f"/media/image/insecure/rs:fit:960:0:0/{cas}.webp?v=1",
        f"/media/image/insecure/rs:fit:320:0:0/{thumb}.webp",
        f"/media/image/insecure/{cas}.webp",
        f"/media/image/insecure/rs:fit:320:0:0/{cas[:5]}/{cas[5:]}.webp",
    ):
        assert await authorize_media_uri({"user_id": 2, "role": "member"}, uri) is True, uri


async def test_media_authz_direct_cas_uses_authenticated_capability_semantics():
    """CAS/thumb paths are session-gated by nginx, not Gallery-ACL checked here."""
    allowed = await authorize_media_uri({"user_id": 2, "role": "member"}, "/media/cas/pr/iv/privatecas.jpg")
    assert allowed is True


# ---------------------------------------------------------------------------
# /api/auth/check — router integration (nginx auth_request subrequest)
# ---------------------------------------------------------------------------


async def test_auth_check_returns_403_for_unauthorized_media_uri(
    unauthed_client, db_session, db_session_factory, mock_redis
):
    """check_auth must 403 when the session is valid but the media URI is not authorized."""
    from core.auth import sign_session

    await _insert_blob(db_session, "sha_router_private", "/mnt/routertest/page1.jpg")
    await _insert_gallery_with_image(
        db_session,
        source_id="g_router_private",
        blob_sha256="sha_router_private",
        created_by_user_id=1,
        visibility="private",
    )

    session_data = sign_session(json.dumps({"user_id": 2, "role": "member"})).encode()
    mock_redis.get.return_value = session_data

    with (
        patch("services.media_authz.async_session", db_session_factory),
    ):
        resp = await unauthed_client.get(
            "/api/auth/check",
            cookies={"vault_session": "2:validtoken"},
            headers={"X-Original-URI": "/media/libraries/routertest/page1.jpg"},
        )
    assert resp.status_code == 403


async def test_auth_check_without_original_uri_still_returns_ok(unauthed_client, mock_redis):
    """check_auth without X-Original-URI (non-nginx callers) keeps its pre-existing behavior."""
    from core.auth import sign_session

    session_data = sign_session(json.dumps({"user_id": 1, "role": "admin"})).encode()
    mock_redis.get.return_value = session_data

    resp = await unauthed_client.get(
        "/api/auth/check",
        cookies={"vault_session": "1:validtoken123"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_auth_check_cas_path_uses_session_only(unauthed_client, mock_redis):
    """Content-addressed media must not enter the URI/Gallery ACL path."""
    from core.auth import sign_session

    session_data = sign_session(json.dumps({"user_id": 2, "role": "member"})).encode()
    mock_redis.get.return_value = session_data

    with patch("routers.auth.authorize_media_uri", side_effect=AssertionError("unexpected URI ACL lookup")):
        resp = await unauthed_client.get(
            "/api/auth/check",
            cookies={"vault_session": "2:validtoken"},
            headers={"X-Original-URI": "/media/cas/aa/bb/hash.jpg"},
        )

    assert resp.status_code == 200
