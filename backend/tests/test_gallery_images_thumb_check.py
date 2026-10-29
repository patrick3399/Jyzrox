"""Thumbnail existence checks in the gallery image list.

The Reader fetches every page of a gallery in one request. Each page used to
stat its thumbnail twice, synchronously, on the event loop; on the NFS data
root that took 1-5 s for an 8k-page gallery and stalled every other request
on the same API worker.
"""

import threading
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import text

from core.config import settings


async def _gallery_with_blobs(db, sid: str, shas: list[str]) -> None:
    await db.execute(
        text(
            "INSERT INTO galleries (source, source_id, title, download_status, pages) "
            "VALUES ('local', :sid, 'T', 'complete', :pages)"
        ),
        {"sid": sid, "pages": len(shas)},
    )
    gid = (await db.execute(text("SELECT id FROM galleries WHERE source_id=:sid"), {"sid": sid})).scalar_one()
    for page, sha in enumerate(shas, start=1):
        await db.execute(
            text(
                "INSERT INTO blobs (sha256, file_size, media_type, width, height, extension, storage, ref_count) "
                "VALUES (:sha, 1, 'image', 10, 20, '.jpg', 'cas', 1) ON CONFLICT DO NOTHING"
            ),
            {"sha": sha},
        )
        await db.execute(
            text("INSERT INTO images (gallery_id, page_num, filename, blob_sha256) VALUES (:g, :p, :f, :sha)"),
            {"g": gid, "p": page, "f": f"{page}.jpg", "sha": sha},
        )
    await db.commit()


def _write_thumb(root: Path, sha: str) -> None:
    directory = root / sha[:2] / sha[2:4] / sha
    directory.mkdir(parents=True)
    (directory / "thumb_160.webp").write_bytes(b"x")


async def test_gallery_images_stats_each_thumb_once_and_off_the_event_loop(client, db_session):
    shas = ["a" * 64, "b" * 64, "c" * 64]
    # Two pages repeat one blob (ADR 0020): still one check for that blob.
    await _gallery_with_blobs(db_session, "thumbstat", [*shas, shas[0]])

    loop_thread = threading.get_ident()
    calls: list[tuple[str, int]] = []
    real_exists = Path.exists

    def recording_exists(self, *args, **kwargs):
        if self.name == "thumb_160.webp":
            calls.append((str(self), threading.get_ident()))
        return real_exists(self, *args, **kwargs)

    with patch.object(Path, "exists", autospec=True, side_effect=recording_exists):
        response = await client.get("/api/library/galleries/local/thumbstat/images")

    assert response.status_code == 200
    assert len(response.json()["images"]) == 4
    checked = [path for path, _ in calls]
    assert len(checked) == len(set(checked)) == len(shas)
    assert all(thread != loop_thread for _, thread in calls)


async def test_gallery_images_thumb_fields_follow_thumb_file_presence(client, db_session, tmp_path, monkeypatch):
    with_thumb, without_thumb = "d" * 64, "e" * 64
    await _gallery_with_blobs(db_session, "thumbpresence", [with_thumb, without_thumb])
    monkeypatch.setattr(settings, "data_thumbs_path", str(tmp_path))
    _write_thumb(tmp_path, with_thumb)

    response = await client.get("/api/library/galleries/local/thumbpresence/images")

    images = {i["file_hash"]: i for i in response.json()["images"]}
    assert images[with_thumb]["thumb_path"] == f"/media/thumbs/dd/dd/{with_thumb}/thumb_160.webp"
    assert images[with_thumb]["thumb_srcset"]
    assert images[without_thumb]["thumb_path"] is None
    assert images[without_thumb]["thumb_srcset"] is None
