# Download Pipeline

## Overview

```
URL submitted
  │
  ▼
POST /api/download/  ─── detect_source(url) → plugin_registry domain lookup
  │
  ├─ _check_source_enabled()   ← Redis feature toggle per source
  ├─ _credential_warning()     ← check credentials (required/recommended/none)
  ├─ INSERT DownloadJob (status=queued)  ← DB first to prevent race condition
  └─ ARQ enqueue("download_job")
         │
         ▼
  Worker: download_job()
  │
  │  1. Plugin selection
  │     plugin_registry.get_handler(url)
  │     → native plugin if available, otherwise fallback to gallery-dl
  │
  │  2. Load credentials
  │     gallery-dl: load ALL credentials → write gallery-dl.json config
  │     native plugin: load only that source's credential
  │
  │  3. Per-source/domain semaphore (concurrency limit)
  │
  │  4. plugin.download(url, dest_dir, credentials, callbacks...)
  │     └─ gallery-dl: spawn subprocess, monitor stdout
  │        each file completed → on_file() callback
  │        progress updates   → on_progress() → update DownloadJob.progress
  │
  │  5. Progressive Import (gallery-dl path)
  │     first file arrives:
  │       → read metadata JSON
  │       → INSERT Gallery (download_status=downloading)
  │     each file arrives:
  │       → SHA256 hash
  │       → store_blob() — hardlink into CAS
  │       → INSERT Image record
  │       → create_library_symlink()
  │       → generate_single_thumbnail()
  │
  │  6. Download complete → importer.finalize()
  │     → update gallery.pages + download_status=complete
  │     → delete temp dir
  │     → enqueue tag_job (if tagger enabled)
  │
  └─ DownloadJob status = "done" / "partial" / "failed"
```

## Storage Architecture

| Layer | Path | Purpose |
|-------|------|---------|
| Temp | `/data/gallery/{source}/{id}/` | gallery-dl download target, deleted after import |
| CAS | `/data/cas/{sha[:2]}/{sha[2:4]}/{sha}.ext` | Content-Addressable Storage, SHA256 filename, hardlink dedup |
| Library | `/data/library/{gallery_id}/` | symlinks → CAS or external path |
| Nginx | `/media/{gallery_id}/{filename}` | serves library symlinks directly |

## Key Design Decisions

- **DB-first enqueue** — DownloadJob row created before ARQ push, prevents worker racing ahead of DB
- **Progressive import** — gallery + images created *during* download, user sees results immediately
- **CAS dedup** — same file across galleries stored once (hardlink), `Blob.ref_count` tracks references
- **Per-source semaphore** — prevents flooding a single site with concurrent requests
- **Cooperative cancel/pause** — Redis keys for soft cancellation, no process killing

## Key Files

| File | Role |
|------|------|
| `backend/routers/download.py` | API endpoint, enqueue, pause/resume/cancel |
| `backend/core/utils.py` | Source detection → plugin_registry |
| `backend/plugins/registry.py` | Plugin registration, source detection, handler lookup |
| `backend/plugins/base.py` | Protocol interfaces (Downloadable, Parseable, etc.) |
| `backend/plugins/builtin/gallery_dl/source.py` | gallery-dl fallback plugin, subprocess management |
| `backend/plugins/builtin/gallery_dl/_subscribe.py` | Subscription checks via `--dump-json --simulate` |
| `backend/plugins/builtin/gallery_dl/_metadata.py` | Metadata parsing, tag normalization, artist extraction |
| `backend/plugins/builtin/gallery_dl/_sites.py` | Data-driven site config registry (`GdlSiteConfig`) |
| `backend/worker/download.py` | Download orchestrator, callbacks, semaphores |
| `backend/worker/progressive.py` | Live gallery creation + file import during download |
| `backend/worker/importer.py` | Post-download import (fallback path), bulk blob storage |
| `backend/services/cas.py` | CAS hardlinking, blob upsert, symlink creation |

---

# Gallery-DL CLI Parameters

## Currently Used (9 flags)

### In `source.py` — download path (6 flags)

| Flag | How Used |
|------|----------|
| `--config-ignore` | Always — ignore user's default gallery-dl config |
| `--config <FILE>` | Always — point to Jyzrox-generated config (`gallery_dl_config` setting) |
| `--write-metadata` | Always — write per-image `.json` metadata (needed for import) |
| `--write-tags` | Always — write tag files |
| `--directory <PATH>` | Always — download destination dir |
| `--sleep-request <N>` | Conditional — only when `download_delay > 0` (from Redis setting) |

### In `_subscribe.py` — subscription check path (3 flags)

| Flag | How Used |
|------|----------|
| `--dump-json` | Always — output JSON instead of downloading |
| `--simulate` | Always — simulate extraction (no file download) |
| `--range 1-50` | Conditional — only on first check (no `last_known`), limits to 50 newest |

## Not Used — High Value

| Flag | Purpose | Jyzrox Benefit |
|------|---------|----------------|
| `--download-archive <FILE>` | Record downloaded URLs, auto-skip duplicates | Subscription updates skip already-downloaded content; saves time and bandwidth |
| `--abort <N>` | Stop after N consecutive skipped files | Combined with archive: subscription check stops at known content boundary |
| `--filesize-min/max <SIZE>` | Filter by file size | Skip thumbnails or oversized files; user-controllable quality/storage |
| `--retries <N>` | Retry failed requests N times (default: 4) | Tune per-source for unreliable sites |
| `--limit-rate <RATE>` | Bandwidth throttle (e.g. `2M`) | Prevent saturating connection during parallel downloads |
| `--filter <EXPR>` | Python expression filter on metadata | Advanced pre-download filtering (e.g. `image_width >= 1000`) |

## Not Used — Medium Value

| Flag | Purpose | Notes |
|------|---------|-------|
| `--no-skip` | Force re-download existing files | Useful for metadata/tag refresh |
| `--ugoira <FMT>` | Convert Pixiv ugoira to webm/mp4/gif | Currently stored as zip frames; could improve playback |
| `--http-timeout <SECS>` | HTTP timeout | Default may be too short for slow sites |
| `--proxy <URL>` | HTTP proxy | Geo-restricted sites |
| `--no-part` | Don't use `.part` temp files | Simplifies progressive import file detection |
| `--sleep-extractor <SECS>` | Delay before starting extractor | Additional rate-limit control |
| `--sleep-429 <SECS>` | Sleep on HTTP 429 response | Auto-backoff on rate limit |

## Not Used — Low Value (already covered or not applicable)

| Flag | Reason Not Needed |
|------|-------------------|
| `-u/-p` (username/password) | Handled via credential system + config JSON |
| `-C` (cookies file) | Cookies written to config JSON |
| `--zip/--cbz` | Conflicts with CAS architecture (needs individual files) |
| `--exec/--exec-after` | Overlaps with progressive import / plugin callbacks |
| `--write-log` | Jyzrox has its own logging |
| `--write-unsupported` | Not useful for automated pipeline |
| Cache flags | gallery-dl cache not relevant to Jyzrox workflow |
| `--no-mtime` | mtime preservation doesn't affect Jyzrox |
| `-U/--update` | gallery-dl updates managed via Docker image build |

## Implementation Priority

1. **`--download-archive`** + **`--abort`** — biggest ROI for subscription workflows
2. **`--retries`** + **`--http-timeout`** — add to `GdlSiteConfig` as per-site tunables
3. **`--filesize-min/max`** — expose in download options UI
4. **`--limit-rate`** — global bandwidth setting in app settings
5. **`--filter`** — advanced feature for power users
