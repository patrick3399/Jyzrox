"""gallery-dl config file generation."""

import json
import logging
import os
from datetime import datetime
from pathlib import Path

from core.config import settings
from plugins.builtin.gallery_dl._archive import archive_dsn_for_job
from plugins.builtin.gallery_dl._config_fragments import _metadata_include, _try_parse_fragment
from plugins.builtin.gallery_dl._extractors import extractor_source_dirs
from services.download_mode import REPAIR, SUBSCRIPTION_INCREMENTAL, effective_mode
from services.download_policy import MediaPolicy
from services.media_formats import VIDEO_EXTENSIONS

logger = logging.getLogger(__name__)


async def _build_gallery_dl_config(
    credentials: dict,
    config_id: str | None = None,
    job_context: str = "manual",
    last_completed_at: datetime | None = None,
    force_full_scan: bool = False,
    target_source_id: str | None = None,
    media: MediaPolicy | None = None,
    persona: dict | None = None,
    mode: str | None = None,
    archive_table: str | None = None,
) -> Path:
    """Write gallery-dl config with v3.0 features: PG archive, native rate-limiting, postprocessors.

    Args:
        credentials: Dict mapping source name -> credential value string.
        config_id: Per-job config isolation key.
        job_context: Legacy: with ``last_completed_at`` and ``force_full_scan`` it
            only decides the mode when ``mode`` is not given.
        last_completed_at: Boundary of a ``subscription_incremental`` run; sets
            ``date-after`` and ``skip: abort:10``.
        force_full_scan: Legacy alias for ``mode="repair"``.
        target_source_id: The site this job actually downloads from. Global
            downloader options (rate) are only applied from this site's
            params — other sites' settings must not leak into the job.
        mode: The job's download mode (``services/download_mode.py``). Decides the
            scan range and the archive: ``subscription_incremental`` stops at the
            boundary, ``repair`` reads and writes ``archive_table`` (a per-job
            shadow) with no boundary, everything else uses the real archive
            with no boundary.
        archive_table: The shadow archive table of a repair run. A repair without
            one runs with no archive at all (the pre-shadow forced re-scan).
        media: Per-job media policy (newest-N files, videos on/off); ``None``
            leaves the config exactly as it was before the option existed.
        persona: ADR 0022 network identity of a persona job — proxy and browser/UA
            for the whole job, overriding every per-site value; ``None`` leaves
            the config unchanged.

    Returns:
        Path to the config file written.
    """
    from plugins.builtin.gallery_dl._sites import all_sites, cookie_writeback_path, gdl_extractor_name, get_site_config

    config: dict = {
        "extractor": {
            "base-directory": settings.data_gallery_path,
            "directory": [],
            # N1: PostgreSQL archive — the table is prepared per job by
            # _ensure_job_archive_table() (init.sql lists the built-in ones). The job id
            # rides on the connection so each row is stamped with its writer.
            "archive": archive_dsn_for_job(settings.gdl_archive_dsn, config_id),
            "archive-table": "{category}",
            # N3: native rate limiting (offloaded from adaptive engine).
            # exp:BASE:START:MAX=VALUE -> sleep(n) = min(START + VALUE*BASE^(n-1), MAX)
            # 429: 30s, 60s, 120s, 240s, capped at 300s
            "sleep-429": "exp:2:0:300=30",
            # retry: 5s, 10s, 20s, 40s, 80s, capped at 120s
            "sleep-retries": "exp:2:0:120=5",
            # N4: content integrity
            "filesize-min": "1k",
            # N10b: file-unique prevents duplicate URLs within a single run
            "file-unique": True,
            # Must live under "extractor": the --Print flags we pass make
            # gallery-dl replace the root-level "postprocessors" list wholesale,
            # so root-level entries never ran (no sha256, no mtime, no JSON).
            "postprocessors": [
                # N5: hash PP — sha256 streamed via --Print ("hashes" is the option HashPP reads)
                {"name": "hash", "hashes": "sha256"},
                # N5: mtime PP — preserves original upload timestamp
                {"name": "mtime"},
                # N10d: metadata PP with include filter (replaces --write-metadata --write-tags)
                {"name": "metadata", "mode": "json", "include": _metadata_include()},
            ],
        },
        "downloader": {
            # N4: adjust-extensions ensures correct file extensions
            "adjust-extensions": True,
        },
    }

    # Custom extractors bundled under plugins/builtin/gallery_dl/extractors.
    # gallery-dl loads modules outside its own package only when this option is
    # set; the trailing None keeps the built-in extractors, and listing ours
    # first matches the in-process load order in _extractors.load_inprocess().
    # Omitted entirely when nothing is bundled, so the emitted config is
    # unchanged for the default install.
    if module_sources := extractor_source_dirs():
        config["extractor"]["module-sources"] = [*module_sources, None]

    # N3: EH rate limits are ban-adjacent — back off harder than the global
    # default. gallery-dl runs both EH domains under the 'exhentai' category
    # ('e-hentai' kept in sync with the cookie injection below).
    for _eh_cat in ("exhentai", "e-hentai"):
        config["extractor"][_eh_cat] = {
            # 429: 60s, 120s, 240s, 480s, capped at 600s
            "sleep-429": "exp:2:0:600=60",
            # retry: 10s, 20s, 40s, 80s, 160s, capped at 300s
            "sleep-retries": "exp:2:0:300=10",
        }

    # The mode decides the scan range and which archive table gallery-dl reads.
    # No archive-mode "memory": it only flushes on an error-free exit, so a
    # single failed file or a killed process dropped every entry of the run.
    mode = effective_mode(
        mode,
        {"job_context": job_context, "last_completed_at": last_completed_at, "force_full_scan": force_full_scan},
    )
    if mode == REPAIR:
        # A repair must fetch every currently visible remote item even if it is
        # already archived, so that the importer can restore missing DB/library
        # rows. It reads an empty per-job shadow table, which still records what
        # it fetches and is merged into the real archive when the run is kept.
        # The ProgressiveImporter keeps existing local images and reorders the
        # combined set, so remote-deleted local-only images remain in the gallery.
        if archive_table:
            config["extractor"]["archive-table"] = archive_table
        else:
            config["extractor"].pop("archive", None)
            config["extractor"].pop("archive-table", None)
    elif mode == SUBSCRIPTION_INCREMENTAL and last_completed_at:
        # Incremental mode: a full download was confirmed before.
        # abort:10 is safe here — 10 consecutive archive hits means we've caught up.
        # An initial run (no boundary) must not abort early: it has to fetch everything.
        config["extractor"]["skip"] = "abort:10"
        from datetime import timedelta

        cutoff = last_completed_at - timedelta(days=1)
        config["extractor"]["date-after"] = cutoff.strftime("%Y-%m-%dT%H:%M:%S")
        # date-after raises StopExtraction at the first post older than the
        # cutoff. Instagram lists pinned posts (usually old) ahead of the feed,
        # so with them included the run stops before reaching anything new.
        # The initial full run already fetched them.
        config["extractor"].setdefault("instagram", {})["pinned"] = False

    # Per-job media policy (options.media). The config file is per job, so
    # root-level extractor keys cannot leak into other jobs.
    if media is not None:
        if media.max_files is not None:
            # Counts files that pass the filter, archived ones included, and
            # stops paginating once the range is exhausted.
            config["extractor"]["file-range"] = f"1-{media.max_files}"
        if not media.include_videos:
            # 'videos' is read by twitter/instagram/facebook and skips video
            # posts before any request; the extension filter covers the rest.
            config["extractor"]["videos"] = False
            exts = ", ".join(repr(e.lstrip(".")) for e in sorted(VIDEO_EXTENSIONS))
            config["extractor"]["file-filter"] = f"extension not in ({exts})"

    # Inject per-site sleep-request via SiteConfigService
    from core.site_config import site_config_service

    all_params = await site_config_service.get_all_download_params()
    for site_cfg in all_sites():
        params = all_params.get(site_cfg.source_id)
        if not params:
            continue
        ext = site_cfg.extractor or site_cfg.source_id
        entry = config["extractor"].setdefault(ext, {})

        if params.sleep_request is not None:
            entry["sleep-request"] = (
                list(params.sleep_request) if isinstance(params.sleep_request, tuple) else params.sleep_request
            )

        # sleep-request only paces API/page requests; file downloads obey "sleep".
        if params.sleep_download is not None:
            entry["sleep"] = (
                list(params.sleep_download) if isinstance(params.sleep_download, tuple) else params.sleep_download
            )

        # N7: per-site browser profile for anti-bot defense
        if params.browser_profile:
            entry["browser"] = params.browser_profile

        # N7: per-site proxy
        if params.proxy_url:
            entry["proxy"] = params.proxy_url

        # N7: bandwidth cap. downloader.rate is a GLOBAL option — apply it only
        # from the job's target site, or one site's cap throttles every site.
        if params.rate_limit and site_cfg.source_id == target_source_id:
            config["downloader"]["rate"] = params.rate_limit

    # Merge credentials on top
    for src, cred_val in credentials.items():
        if not cred_val:
            continue
        cfg = get_site_config(src)
        ext = gdl_extractor_name(src)

        cookies_applied = False
        fragment = _try_parse_fragment(cred_val)
        if fragment is not None:
            config["extractor"].setdefault(ext, {}).update(fragment)
            if "cookies" in fragment:
                for extra in cfg.extra_extractors:
                    config["extractor"].setdefault(extra, {})["cookies"] = fragment["cookies"]
                cookies_applied = True
        else:
            if cfg.credential_type == "refresh_token":
                config["extractor"].setdefault(ext, {})["refresh-token"] = cred_val
            elif cfg.credential_type == "cookies":
                try:
                    cookies = json.loads(cred_val)
                    config["extractor"].setdefault(ext, {})["cookies"] = cookies
                    for extra in cfg.extra_extractors:
                        config["extractor"].setdefault(extra, {})["cookies"] = cookies
                    cookies_applied = True
                except json.JSONDecodeError, TypeError:
                    logger.warning("[gallery_dl] invalid cookie JSON for source %s, skipping", src)

        # N8: cookies-update must be an explicit export path — a bare True tells
        # gallery-dl to rewrite the *input* cookies file, which does not exist
        # when cookies are passed inline as a dict (silent no-op). The worker's
        # _writeback_cookies() reads this same path after the job finishes.
        # Set on extra extractors too: EH jobs run under exhentai/e-hentai categories.
        if cookies_applied and config_id:
            cookie_export = cookie_writeback_path(config_id, src)
            for name in (ext, *cfg.extra_extractors):
                config["extractor"].setdefault(name, {})["cookies-update"] = cookie_export

    # ADR 0022: a persona job is one identity end to end. Child extractors and
    # file downloads must not fall back to the host's own route or a per-site
    # proxy/browser, so the persona is set at the root and per-site values go.
    # After the credentials loop: credential fragments are merged with
    # .update(fragment) and may carry their own proxy/user-agent.
    if persona is not None:
        for entry in config["extractor"].values():
            if isinstance(entry, dict):
                for key in ("proxy", "browser", "user-agent"):
                    entry.pop(key, None)
        if persona.get("proxy_url"):
            config["extractor"]["proxy"] = persona["proxy_url"]
            config["downloader"]["proxy"] = persona["proxy_url"]
        if persona.get("browser_profile"):
            config["extractor"]["browser"] = persona["browser_profile"]
        elif persona.get("user_agent"):
            config["extractor"]["user-agent"] = persona["user_agent"]

    # N6: ugoira PP for Pixiv (convert animated illustrations to MP4)
    if "pixiv" in credentials and credentials["pixiv"]:
        config["extractor"]["postprocessors"].append(
            {
                "name": "ugoira",
                "ffmpeg-output": True,
                "ffmpeg-args": ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-an"],
                "ffmpeg-twopass": False,
                "keep-files": False,
                "extension": "mp4",
            }
        )

    config_dir = Path(settings.gallery_dl_config).parent
    config_path = config_dir / f"gallery-dl-{config_id}.json" if config_id else Path(settings.gallery_dl_config)
    tmp_path = config_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(config, indent=2))
    os.rename(tmp_path, config_path)
    return config_path
