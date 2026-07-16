"""Regression tests for F6/BR-006 — per-gallery ACL on path-addressed media URIs.

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
        text("INSERT INTO images (gallery_id, page_num, blob_sha256) VALUES (:gid, 1, :sha)"),
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
        patch("services.media_authz.get_redis", return_value=mock_redis),
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
        patch("services.media_authz.get_redis", return_value=mock_redis),
    ):
        allowed = await authorize_media_uri({"user_id": 1, "role": "member"}, "/media/libraries/mine/page1.jpg")
    assert allowed is True


async def test_media_authz_unregistered_mnt_path_denied(db_session, db_session_factory, mock_redis):
    """A /mnt path with no matching blob at all is denied (closes #68 full-tree browsing)."""
    with (
        patch("services.media_authz.async_session", db_session_factory),
        patch("services.media_authz.get_redis", return_value=mock_redis),
    ):
        allowed = await authorize_media_uri(
            {"user_id": 2, "role": "member"}, "/media/libraries/never/registered/anywhere.jpg"
        )
    assert allowed is False


async def test_media_authz_path_traversal_rejected(db_session, db_session_factory, mock_redis):
    """A '..' path segment is rejected outright, without ever touching the DB."""
    with (
        patch("services.media_authz.async_session", db_session_factory),
        patch("services.media_authz.get_redis", return_value=mock_redis),
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


async def test_media_authz_imgproxy_cas_source_allowed(mock_redis):
    """An imgproxy source under local:///cas/ is allowed (no gallery ACL check applies)."""
    b64 = _b64_source("local:///cas/ab/cdef1234.jpg")
    uri = f"/media/image/insecure/rs:fill:200:200/{b64}.webp"
    allowed = await authorize_media_uri({"user_id": 2, "role": "member"}, uri)
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
        patch("services.media_authz.get_redis", return_value=mock_redis),
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
