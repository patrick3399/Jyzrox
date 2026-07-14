"""Background recursive size calculation for physical Explorer folders."""

import asyncio
import json

from core.database import AsyncSessionLocal
from db.models import LibraryPath
from services.explorer_filesystem import (
    folder_stats_key,
    relative_posix,
    resolve_library_relative,
    scan_folder_stats,
)


async def explorer_folder_stats_job(ctx: dict, library_id: int, relative_path: str = "") -> dict:
    async with AsyncSessionLocal() as db:
        library = await db.get(LibraryPath, library_id)
        if library is None or not library.enabled:
            return {"status": "missing_library"}
        from pathlib import Path

        root = Path(library.path).resolve(strict=False)
        if not root.is_dir():
            return {"status": "unavailable"}
        directory = resolve_library_relative(root, relative_path, require_directory=True)
        canonical_relative = relative_posix(root, directory)

    stats = await asyncio.to_thread(scan_folder_stats, root, directory)
    await ctx["redis"].setex(
        folder_stats_key(library_id, canonical_relative),
        86400,
        json.dumps(stats),
    )
    return {"status": "ok", **stats}
