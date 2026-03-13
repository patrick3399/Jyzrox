"""Gallery-dl subscription support — check for new works via --dump-json --simulate."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime

from plugins.models import NewWork, PluginMeta

logger = logging.getLogger(__name__)

_TIMEOUT = 120  # seconds


async def _write_temp_config(source: str, credentials: str | dict | None) -> str | None:
    """Write a temporary gallery-dl config with cookies. Returns path or None."""
    if not credentials:
        return None

    cookies: dict
    if isinstance(credentials, str):
        try:
            cookies = json.loads(credentials)
        except (json.JSONDecodeError, TypeError):
            return None
    elif isinstance(credentials, dict):
        cookies = credentials
    else:
        return None

    from plugins.builtin.gallery_dl.source import _source_to_extractor

    extractor_name = _source_to_extractor(source)
    config = {
        "extractor": {
            extractor_name: {
                "cookies": cookies,
            },
        },
    }

    path = f"/tmp/gdl-sub-{source}-{uuid.uuid4().hex[:8]}.json"
    with open(path, "w") as f:
        json.dump(config, f)
    return path


async def check_gdl_new_works(
    source: str,
    source_id: str,
    last_known: str | None,
    credentials: str | dict | None,
) -> list[NewWork]:
    """Check for new works on a gallery-dl supported site.

    Uses `gallery-dl --dump-json --simulate` to enumerate posts without downloading.
    Parses JSON output line by line, extracts item IDs, and stops at the last_known boundary.
    """
    from plugins.builtin.gallery_dl._sites import get_site_config

    site_cfg = get_site_config(source)
    if not site_cfg or not site_cfg.subscribe_id_key or not site_cfg.subscribe_url_tpl:
        logger.warning("[gdl_subscribe] unsupported source: %s", source)
        return []

    id_key = site_cfg.subscribe_id_key
    url_tpl = site_cfg.subscribe_url_tpl
    url = url_tpl.format(source_id)

    cmd = ["gallery-dl", "--dump-json", "--simulate"]

    # First check (no last_known) — cap at 50 items to avoid pulling full history
    if last_known is None:
        cmd.extend(["--range", "1-50"])

    config_path = await _write_temp_config(source, credentials)
    if config_path:
        cmd.extend(["--config", config_path])

    cmd.append(url)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        new_works: list[NewWork] = []
        seen_ids: dict[str, bool] = {}  # ordered dict for dedup

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=_TIMEOUT,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            logger.error("[gdl_subscribe] timeout after %ds for %s/%s", _TIMEOUT, source, source_id)
            return []

        if proc.returncode != 0:
            err_msg = (stderr or b"").decode(errors="replace").strip()
            # Some non-zero exits still produce valid output (e.g., partial results)
            if not stdout:
                logger.warning("[gdl_subscribe] gallery-dl failed for %s/%s (rc=%d): %s",
                               source, source_id, proc.returncode, err_msg[:200])
                return []

        for line in stdout.decode(errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            # gallery-dl --dump-json outputs JSON arrays: [type, url_or_dir, metadata]
            # type 1 = directory entry, type 2 = file entry
            if not isinstance(entry, list) or len(entry) < 3:
                continue
            entry_type = entry[0]
            if entry_type != 2:
                continue

            metadata = entry[2] if isinstance(entry[2], dict) else {}
            item_id = str(metadata.get(id_key, ""))
            if not item_id:
                continue

            # Stop at the incremental boundary
            if last_known is not None and item_id == last_known:
                break

            # Dedup (e.g., multi-image tweets produce multiple entries with same tweet_id)
            if item_id in seen_ids:
                continue
            seen_ids[item_id] = True

            # Build the individual work URL
            work_url = metadata.get("url", url)
            title = metadata.get("description", "") or metadata.get("title", "") or item_id

            posted_at = None
            for date_key in ("date", "created_at", "date_utc"):
                raw_date = metadata.get(date_key)
                if raw_date:
                    if isinstance(raw_date, str):
                        try:
                            posted_at = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
                        except ValueError:
                            pass
                    break

            new_works.append(NewWork(
                url=work_url,
                title=title[:200],
                source_id=item_id,
                posted_at=posted_at,
            ))

        return new_works

    except Exception as exc:
        logger.error("[gdl_subscribe] error checking %s/%s: %s", source, source_id, exc)
        return []
    finally:
        if config_path:
            try:
                os.unlink(config_path)
            except OSError:
                pass


class GalleryDlSubscribableProxy:
    """Lightweight proxy that implements the Subscribable protocol for a specific gallery-dl site."""

    def __init__(self, source: str, gdl_meta: PluginMeta) -> None:
        self._source = source
        # Create a site-specific meta (needed by the protocol)
        self.meta = PluginMeta(
            name=f"gallery-dl ({source})",
            source_id=source,
            version=gdl_meta.version,
            description=f"Subscription support for {source} via gallery-dl",
            url_patterns=[],
            credential_schema=[],
        )

    async def check_new_works(
        self,
        artist_id: str,
        last_known: str | None,
        credentials: dict | str | None,
    ) -> list[NewWork]:
        return await check_gdl_new_works(self._source, artist_id, last_known, credentials)
