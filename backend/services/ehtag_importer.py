"""EhTagTranslation CDN importer service."""

import logging

import httpx
from sqlalchemy.dialects.postgresql import insert as pg_insert

from core.database import async_session
from db.models import TagTranslation

logger = logging.getLogger(__name__)

EHTAG_CDN_URL = "https://cdn.jsdelivr.net/gh/EhTagTranslation/DatabaseReleases@latest/db.text.json"

# Namespaces to import (skip 'rows' which is metadata)
_VALID_NAMESPACES = frozenset({
    "artist", "character", "parody", "group", "language",
    "misc", "other", "reclass", "cosplayer",
    "female", "male", "mixed",
})


async def import_ehtag_translations() -> int:
    """Fetch EhTagTranslation database and upsert all translations.

    Returns the number of translations upserted.
    """
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(EHTAG_CDN_URL)
        resp.raise_for_status()
        payload = resp.json()

    rows_to_upsert: list[dict] = []
    for ns_entry in payload.get("data", []):
        namespace = ns_entry.get("namespace", "")
        if namespace not in _VALID_NAMESPACES:
            continue
        data = ns_entry.get("data", {})
        for tag_name, tag_info in data.items():
            if not tag_name or not isinstance(tag_info, dict):
                continue
            translation = tag_info.get("name", "")
            if not translation:
                continue
            rows_to_upsert.append({
                "namespace": namespace,
                "name": tag_name,
                "language": "zh",
                "translation": translation,
            })

    if not rows_to_upsert:
        return 0

    async with async_session() as session:
        CHUNK = 1000
        for i in range(0, len(rows_to_upsert), CHUNK):
            chunk = rows_to_upsert[i : i + CHUNK]
            stmt = (
                pg_insert(TagTranslation)
                .values(chunk)
                .on_conflict_do_update(
                    index_elements=["namespace", "name", "language"],
                    set_={"translation": pg_insert(TagTranslation).excluded.translation},
                )
            )
            await session.execute(stmt)
        await session.commit()

    logger.info("Imported %d EhTag translations", len(rows_to_upsert))
    return len(rows_to_upsert)
