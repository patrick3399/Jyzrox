#!/usr/bin/env python3
"""Backfill canonical newest-first ordering for gallery-dl social galleries.

Dry-run by default:
    python db/backfill_social_order.py

Apply changes:
    python db/backfill_social_order.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))


def _preview(items) -> list[str]:
    return [f"{img.page_num}:{img.filename}" for img in items[:10]]


async def main() -> None:
    from sqlalchemy import select

    from core.database import AsyncSessionLocal
    from core.social_order import is_social_source, reorder_social_gallery_images, social_image_sort_key
    from db.models import Gallery, Image
    from plugins.builtin.gallery_dl._sites import GDL_SITES

    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write changes instead of dry-run")
    parser.add_argument("--limit", type=int, default=0, help="maximum number of changed galleries to report/process")
    parser.add_argument("--batch-galleries", type=int, default=10, help="commit interval when --apply is used")
    args = parser.parse_args()

    social_sources = sorted({site.source_id for site in GDL_SITES if site.category == "social"})
    changed_galleries = 0
    processed_since_commit = 0

    async with AsyncSessionLocal() as session:
        galleries = (
            (
                await session.execute(
                    select(Gallery.id, Gallery.source, Gallery.source_id)
                    .where(Gallery.source.in_(social_sources))
                    .order_by(Gallery.source.asc(), Gallery.source_id.asc())
                )
            )
            .all()
        )

        for gallery in galleries:
            if not is_social_source(gallery.source):
                continue
            images = (
                (
                    await session.execute(
                        select(Image)
                        .where(Image.gallery_id == gallery.id, Image.visibility == "active")
                        .order_by(Image.page_num.asc(), Image.id.asc())
                    )
                )
                .scalars()
                .all()
            )
            ordered = sorted(images, key=social_image_sort_key)
            if [img.id for img in images] == [img.id for img in ordered]:
                continue

            changed_galleries += 1
            print(f"{gallery.source}/{gallery.source_id} gallery_id={gallery.id} pages={len(images)}")
            print(f"  before: {_preview(images)}")
            print(f"  after : {_preview(ordered)}")

            if args.apply:
                await reorder_social_gallery_images(session, gallery.id, gallery.source)
                processed_since_commit += 1
                if processed_since_commit >= args.batch_galleries:
                    await session.commit()
                    processed_since_commit = 0
            else:
                session.expire_all()

            if args.limit and changed_galleries >= args.limit:
                break

        if args.apply:
            await session.commit()

    mode = "updated" if args.apply else "would update"
    print(f"Done: {mode} {changed_galleries} social gallery/galleries")


if __name__ == "__main__":
    asyncio.run(main())
