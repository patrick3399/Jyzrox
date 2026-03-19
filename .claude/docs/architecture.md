# Jyzrox Architecture (v0.12)

> Codebase audit, 2026-03-20 (updated). Read from source files — do not update manually; regenerate from source.

---

## Service Topology

### Docker Compose Services

| Service | Image / Build | Port | Networks | Resource Limits |
|---------|--------------|------|----------|-----------------|
| `nginx` | `./nginx` | `${HTTP_PORT:-35689}:80` | frontend | 1 CPU / 256 MB |
| `api` | `./backend` (uvicorn, port 8000) | internal | frontend + backend | 2 CPU / 2 GB |
| `worker` | `./backend` (arq worker.WorkerSettings) | — | frontend + backend | 2 CPU / 2 GB |
| `pwa` | `./pwa` (Next.js, port 3000) | internal | frontend | 1 CPU / 512 MB |
| `postgres` | `postgres:18-alpine` | internal | backend | 2 CPU / 2 GB |
| `redis` | `redis:8-alpine` | internal | backend | 1 CPU / 1 GB |
| `tagger` | `./tagger` (FastAPI :8100, ONNX inference) | internal | backend | — |

> `tagger` service is optional — started only with `--profile tagging`. Worker calls it via HTTP (`POST /predict`) and gracefully skips if offline.

> 所有服務均套用 `security_opt: ["no-new-privileges:true"]`，防止容器內進程提權。

### Networks

| Network | Name | Internal |
|---------|------|----------|
| `frontend` | `vault_frontend` | No |
| `backend` | `vault_backend` | Yes (no external access) |

### Volumes

| Volume | Usage |
|--------|-------|
| `app_data` | Shared `/data` mount (gallery files, thumbs, CAS, avatars) |
| `postgres_data` | PostgreSQL data directory |
| `redis_data` | Redis AOF persistence |
| `tagger_models` | HuggingFace model cache for WD14 tagger |

### Container UID

| Environment | UID:GID | Mechanism |
|-------------|---------|-----------|
| Production | `1042:1042` (appuser) | `entrypoint.sh` via gosu |
| Dev override | `1000:1000` | `docker-compose.override.yml` |

### Filesystem Layout

```
/data/
├── gallery/
│   ├── ehentai/{gid}/        # EH native downloads
│   └── pixiv/{illust_id}/    # Pixiv artwork downloads
├── cas/                      # Content-Addressable Storage (sha256-keyed blobs)
├── thumbs/{xx}/{sha256}/     # 160/360/720px WebP thumbnails
├── avatars/                  # User avatar uploads
├── library/                  # Symlinks to CAS blobs for library access
├── training/                 # Kohya export datasets
└── archive/                  # Archived gallery data
/mnt/                         # Host-mounted external library paths (read-only)
```

---

## Backend (FastAPI)

Entry point: `backend/main.py`
Middlewares: `CORSMiddleware`, `CSRFMiddleware`, `RateLimitMiddleware`

### Router Map

| Prefix | File | Auth | Description |
|--------|------|------|-------------|
| `/api/auth` | `routers/auth.py` | Public + session | Login, logout, setup, sessions, profile, avatar, password |
| `/api/system` | `routers/system.py` | Session | Health, info, cache stats/clear |
| `/api/eh` | `plugins/builtin/ehentai/browse.py` (dynamic) | Session | EH search, gallery, images, proxy, favorites, popular, toplists |
| `/api/pixiv` | `plugins/builtin/pixiv/_browse.py` (dynamic) | Session | Pixiv search, illust, user, following, image proxy |
| `/api/library` | `routers/library.py` | Session | Gallery CRUD, images, tags, progress, artists, image browser, trash (soft-delete) |
| `/api/download` | `routers/download.py` | Session | Enqueue, list/cancel/retry jobs, stats, pause/resume, dashboard (admin) |
| `/api/settings` | `routers/settings.py` | Session | Credentials, API tokens, feature flags, EH site toggle, rate limit, site credential save, URL detect |
| `/api/ws` | `routers/ws.py` | Session | WebSocket at `/api/ws/ws` |
| `/api/search` | `routers/search.py` | Session | Full-text gallery search, saved searches |
| `/api/tags` | `routers/tag.py` | Session | Tag listing, aliases, implications, autocomplete, translations (OpenCC zh-TW), blocked, retag, EhTag import |
| `/api/import` | `routers/import_router.py` | Session | Local import, library paths, rescan, file browser, monitor, scheduled scan |
| `/api/export` | `routers/export.py` | Session | Kohya zip export |
| `/api/external/v1` | `routers/external.py` | `X-API-Token` header | External API for third-party integrations |
| `/api/history` | `routers/history.py` | Session | Browse history CRUD |
| `/api/plugins` | `routers/plugins.py` | Session | List plugins with credential_flows, browse schema |
| `/api/artists` | `routers/artists.py` | Session | Followed artists (Pixiv/EH) |
| `/api/collections` | `routers/collections.py` | Session | Collection CRUD, add/remove galleries |
| `/api/scheduled-tasks` | `routers/scheduled_tasks.py` | Session | Scheduled task listing, enable/disable, manual run |
| `/api/dedup` | `routers/dedup.py` | Session | Dedup stats, review list, keep/whitelist/skip actions, scan start/stop/progress |
| `/api/subscriptions` | `routers/subscriptions.py` | Session | Subscription CRUD, manual check trigger |
| `/api/subscription-groups` | `routers/subscription_groups.py` | Admin | Subscription group CRUD, run/pause/resume actions |
| `/api/users` | `routers/users.py` | Admin | User management CRUD |
| `/opds` | `routers/opds.py` | HTTP Basic Auth | OPDS catalog for e-readers |
| `/api/rss` | `routers/rss.py` | API Token (query param) | RSS/Atom feed for gallery updates and subscription activity |
| `/api/logs` | `routers/logs.py` | Admin | Log viewer: entries, level control, retention settings |
| `/api/admin/sites` | `routers/site_config.py` | Admin | Per-site download config: list, get, update overrides, reset field, reset adaptive, probe URL (gallery-dl --dump-json analysis with SSRF protection), save field mappings |
| `/api/admin/gallery-dl` | `routers/gallery_dl_admin.py` | Admin | Gallery-dl venv: version, upgrade, rollback |
| `/api/health` | `main.py` inline | Public | Liveness probe |

---

### Database Schema

#### Tables

| Table | Description | Key Columns |
|-------|-------------|-------------|
| `users` | User accounts | `id`, `username` UNIQUE, `password_hash`, `role`, `locale`, `avatar_style` |
| `galleries` | Gallery records | `id`, `(source, source_id)` UNIQUE, `title`, `tags_array TEXT[]`, `download_status`, `artist_id`, `library_path`, `visibility TEXT DEFAULT 'public'`, `created_by_user_id BIGINT REFERENCES users(id)`, `deleted_at TIMESTAMPTZ` (soft-delete) |
| `blobs` | CAS file store | `sha256` PK, `file_size`, `media_type`, `width`, `height`, `duration`, `phash*`, `extension`, `storage`, `ref_count`, `thumbhash TEXT` (base64 thumbhash for image placeholders) |
| `images` | Gallery pages | `id`, `gallery_id` FK, `page_num`, `blob_sha256` FK, `tags_array TEXT[]`, `added_at TIMESTAMPTZ` (denormalized from gallery) |
| `tags` | Tag registry | `id`, `(namespace, name)` UNIQUE, `count` |
| `tag_aliases` | Tag alias map | `(alias_namespace, alias_name)` PK → `canonical_id` FK |
| `tag_implications` | Tag inference rules | `(antecedent_id, consequent_id)` PK |
| `gallery_tags` | Gallery↔Tag join | `(gallery_id, tag_id)` PK, `confidence`, `source` |
| `image_tags` | Image↔Tag join | `(image_id, tag_id)` PK, `confidence` |
| `download_jobs` | ARQ job tracking | `id` UUID PK, `user_id` FK, `url`, `source`, `status` (queued/running/done/failed/cancelled/paused/partial), `progress` JSONB (may contain `failed_pages`, `permanently_failed`), `error`, `retry_count SMALLINT`, `max_retries SMALLINT`, `next_retry_at`, `gallery_id BIGINT FK` (progressive import link), `subscription_id BIGINT FK` (subscription → job link) |
| `read_progress` | Per-gallery read cursor | `(user_id, gallery_id)` PK, `last_page`, `last_read_at` |
| `credentials` | Source credentials (encrypted) | `source` PK, `credential_type`, `value_encrypted` BYTEA |
| `api_tokens` | External API tokens | `id` UUID PK, `user_id` FK, `token_hash` UNIQUE, `token_plain`, `expires_at` |
| `browse_history` | EH browse history | `id`, `(user_id, source, source_id)` UNIQUE, `gid`, `token`, `viewed_at` |
| `saved_searches` | Persisted search queries | `id`, `user_id` FK, `name`, `query`, `params` JSONB |
| `tag_translations` | Tag i18n (zh default) | `(namespace, name, language)` PK, `translation` |
| `blocked_tags` | Per-user tag blocklist | `id`, `(user_id, namespace, name)` UNIQUE |
| `library_paths` | User-configured scan paths | `id`, `path` UNIQUE, `label`, `enabled`, `monitor` |
| `plugin_config` | Plugin enable/config | `source_id` PK, `enabled`, `config_json` JSONB |
| `audit_logs` | Security audit trail (schema-only; no ORM model; application code in `core/audit.py` via raw SQL) | `id`, `user_id` FK, `action`, `resource_type`, `resource_id`, `details` JSONB, `ip_address`, `created_at` |
| `subscription_groups` | Group-based subscription scheduling (M3) | `id SERIAL PK`, `name`, `schedule TEXT` (cron), `concurrency SMALLINT`, `enabled`, `priority SMALLINT`, `is_system BOOLEAN`, `status` (idle/running/paused), `last_run_at`, `last_completed_at`, `created_at`, `updated_at` |
| `subscriptions` | Artist/source subscriptions | `id`, `(user_id, url)` UNIQUE, `name`, `url`, `source`, `source_id`, `avatar_url`, `enabled`, `auto_download`, `cron_expr`, `last_checked_at`, `last_item_id`, `last_status`, `last_error`, `next_check_at`, `created_at`, `batch_total INT`, `batch_enqueued INT`, `last_job_id UUID FK`, `group_id INT FK → subscription_groups` |
| `collections` | Gallery collections | `id`, `user_id` FK, `name`, `description`, `cover_gallery_id` |
| `collection_galleries` | Collection↔Gallery join | `(collection_id, gallery_id)` PK, `position` |
| `excluded_blobs` | Per-gallery blob exclusions | `(gallery_id, blob_sha256)` PK, `excluded_at` |
| `blob_relationships` | Dedup pair store | `id BIGSERIAL PK`, `sha_a / sha_b` FK → `blobs` (`CHECK sha_a < sha_b`, `UNIQUE` pair), `hamming_dist SMALLINT`, `relationship TEXT` (`needs_t2`/`quality_conflict`/`variant`/`whitelisted`/`needs_t3`/`resolved`), `suggested_keep TEXT`, `reason TEXT`, `diff_score FLOAT`, `diff_type TEXT`, `tier SMALLINT`, `created_at`, `updated_at` |
| `user_favorites` | Per-user gallery favorites | `(user_id, gallery_id)` PK, `created_at` |
| `user_ratings` | Per-user gallery ratings | `(user_id, gallery_id)` PK, `rating SMALLINT CHECK (0–5)`, `rated_at TIMESTAMPTZ` |
| `user_reading_list` | Per-user reading list (read later) | `(user_id, gallery_id)` PK, `added_at TIMESTAMPTZ` |
| `user_image_favorites` | Per-user image favorites | `(user_id, image_id)` PK, `created_at TIMESTAMPTZ` |
| `site_configs` | Per-site download tuning (M1) | `source_id` PK, `overrides JSONB` (manual), `adaptive JSONB` (auto-tune), `auto_probe JSONB` (M2 prep), `updated_at` |

> **Note:** Tables `collections`, `collection_galleries`, and `excluded_blobs` are created via Alembic migrations (`0005b`, `0007`), not in `db/init.sql`. The `audit_logs` table is also migration-only (`0005`). `blob_relationships` is created in `db/init.sql`. `user_ratings`, `blobs.thumbhash`, `images.added_at`, `galleries.deleted_at`, and `user_image_favorites` are added via `ALTER TABLE` / `CREATE TABLE IF NOT EXISTS` in `db/init.sql`.

#### Key Indexes

| Index | Table | Type | Purpose |
|-------|-------|------|---------|
| `idx_galleries_tags_gin` | `galleries` | GIN | `tags_array @>` tag search |
| `idx_images_tags_gin` | `images` | GIN | per-image tag search |
| `idx_galleries_title_trgm` | `galleries` | GIN (trgm) | fuzzy title search |
| `idx_galleries_title_jpn_trgm` | `galleries` | GIN (trgm) | fuzzy Japanese title search |
| `idx_blobs_phash_q{0-3}` | `blobs` | BTree | pHash pigeonhole dedup |
| `idx_galleries_added_at_id` | `galleries` | BTree | keyset pagination |
| `idx_galleries_rating_id` | `galleries` | BTree | keyset pagination |
| `idx_galleries_pages_id` | `galleries` | BTree | keyset pagination |
| `idx_images_added_at_id` | `images` | BTree | keyset pagination for image browser |
| `idx_download_jobs_retry` | `download_jobs` | BTree (partial) | Retry query: `WHERE status IN ('failed', 'partial')` |
| `idx_galleries_deleted_at` | `galleries` | BTree (partial) | Soft-delete query: `WHERE deleted_at IS NOT NULL` |
| `idx_uif_image` | `user_image_favorites` | BTree | Image favorite lookup |
| `idx_subscriptions_group` | `subscriptions` | BTree | Group-based subscription lookup |

---

### ORM Models

All models are in `backend/db/models.py`.

| Class | Table |
|-------|-------|
| `User` | `users` |
| `Gallery` | `galleries` |
| `Blob` | `blobs` |
| `Image` | `images` |
| `Tag` | `tags` |
| `TagAlias` | `tag_aliases` |
| `TagImplication` | `tag_implications` |
| `GalleryTag` | `gallery_tags` |
| `ImageTag` | `image_tags` |
| `DownloadJob` | `download_jobs` |
| `ReadProgress` | `read_progress` |
| `Credential` | `credentials` |
| `ApiToken` | `api_tokens` |
| `BrowseHistory` | `browse_history` |
| `SavedSearch` | `saved_searches` |
| `TagTranslation` | `tag_translations` |
| `BlockedTag` | `blocked_tags` |
| `LibraryPath` | `library_paths` |
| `PluginConfig` | `plugin_config` |
| `Subscription` | `subscriptions` |
| `SubscriptionGroup` | `subscription_groups` |
| `Collection` | `collections` |
| `CollectionGallery` | `collection_galleries` |
| `ExcludedBlob` | `excluded_blobs` |
| `BlobRelationship` | `blob_relationships` |
| `UserFavorite` | `user_favorites` |
| `UserRating` | `user_ratings` |
| `UserReadingList` | `user_reading_list` |
| `UserImageFavorite` | `user_image_favorites` |
| `SiteConfig` | `site_configs` |

---

### Worker Pipeline (ARQ)

Entry: `arq worker.WorkerSettings` (package: `backend/worker/` with `__init__.py`, `constants.py`, `helpers.py`, `download.py`, `importer.py`, `scan.py`, `tagging.py`, `tag_helpers.py`, `thumbnail.py`, `reconciliation.py`, `subscription.py`, `subscription_group.py`, `dedup.py`, `dedup_scan.py`, `dedup_tier1.py`, `dedup_tier2.py`, `dedup_tier3.py`, `dedup_helpers.py`, `thumbhash_backfill.py`, `retry.py`, `progressive.py`, `trash.py`, `ehtag_sync.py`)

> **`helpers.py` shared utilities:** `compute_arq_job_id(job_id, retry_count)` generates unique ARQ job IDs; `enqueue_download_job(arq_pool, job, arq_job_id)` standardizes download job enqueue parameters; `check_disk_space(path, min_free_gb)` returns `(ok, free_gb)` with fail-open on OSError; `acquire_lock(redis, key, ttl)` / `release_lock(redis, key, value)` distributed lock with Lua compare-and-delete; `validate_cron(expr)` in `core/utils.py` — shared cron validation raising HTTPException(400).

#### Job Functions

| Function | Trigger | Description |
|----------|---------|-------------|
| `download_job` | API enqueue | Download gallery via plugin registry; disk space pre-flight (Redis flag + syscall fallback) before semaphore acquire; falls back to gallery-dl subprocess |
| `import_job` | After `download_job` | Scan directory, hash files, upsert gallery/images/tags to DB, enqueue thumbnail |
| `local_import_job` | `/api/import/` POST | Import a local directory into the library (copy mode) |
| `rescan_library_job` | Manual / scheduled | Full rescan of all configured library paths |
| `rescan_gallery_job` | `/api/import/rescan/{id}` | Rescan a single gallery's files |
| `tag_job` | After import | AI tagging (WD14 stub; disabled when `tag_model_enabled=false`) |
| `thumbnail_job` | After import | Generate 160/360/720px WebP thumbnails via Pillow; first-frame extract for video |
| `reconciliation_job` | Manual | Reconcile CAS ref counts and clean orphaned blobs |
| `auto_discover_job` | `/api/import/discover` | Auto-discover new galleries under all library paths |
| `rescan_by_path_job` | File watcher event | Rescan a specific directory triggered by inotify/polling |
| `rescan_library_path_job` | `/api/import/rescan/path/{id}` | Rescan one configured library path |
| `scheduled_scan_job` | ARQ cron | Periodic full library scan (interval from `library_scan_interval_hours`) |
| `toggle_watcher_job` | `/api/import/monitor/toggle` | Start/stop the LibraryWatcher file monitor |
| `subscription_scheduler` | ARQ cron (every minute) | 1-minute dispatcher: queries enabled+idle groups by priority, checks cron schedule via `_cron_is_due()`, atomically claims groups (`UPDATE WHERE status='idle' RETURNING`), enqueues `check_subscription_group` |
| `check_subscription_group` | Via `subscription_scheduler` / manual | Check all enabled+auto_download subscriptions in a group with `asyncio.Semaphore(concurrency)` + 30-min deadline (`asyncio.timeout`); calls `_enqueue_for_subscription()` per sub; resets group to idle on completion or exception |
| `check_followed_artists` | Manual trigger only (per-user) | Legacy: checks ungrouped subscriptions only (`group_id IS NULL`); kept for per-user manual trigger via API |
| `check_single_subscription` | `/api/subscriptions/{id}/check` | Check a single subscription for new works |
| `batch_import_job` | `/api/import/batch/start` | Batch import multiple local directories |
| `dedup_scan_job` | Manual (`POST /api/dedup/scan/start`) / scheduled | Orchestrates full dedup pipeline: runs Tier 1 → Tier 2 → optionally Tier 3; tracks progress in Redis |
| `dedup_tier1_job` | Via `dedup_scan_job` | pHash pigeonhole scan → Hamming distance → writes `blob_relationships` |
| `dedup_tier2_job` | Via `dedup_scan_job` | Heuristic classification: fills `relationship` (`quality_conflict`/`variant`) + `suggested_keep` |
| `dedup_tier3_job` | Via `dedup_scan_job` (when `dedup_opencv_enabled`) | OpenCV pixel-diff validates `needs_t3` pairs → confirms or resolves as false positive |
| `thumbhash_backfill_job` | Manual | Batch-generates base64 thumbhash for existing blobs missing `thumbhash`; reads `thumb_160.webp` via Pillow + `thumbhash` library; processes in batches of 500 using keyset pagination on `sha256` |
| `rate_limit_schedule_job` | ARQ cron (*/10) | Checks rate limit schedule config in Redis; sets/clears `rate_limit:schedule:active` flag based on current hour vs configured start/end hours |
| `retry_failed_downloads_job` | ARQ cron (*/15) | **Stale reaper** marks running jobs >60min and queued jobs >30min as failed; then scans failed/partial jobs with `retry_count < max_retries`; re-queues with exponential backoff; `LIMIT 10` + `FOR UPDATE SKIP LOCKED`; skips entirely when `system:disk_low` Redis flag is set |
| `trash_gc_job` | ARQ cron | Permanently deletes galleries whose `deleted_at` has exceeded the retention period; when trash is disabled, hard-deletes all soft-deleted galleries |
| `ehtag_sync_job` | ARQ cron (`30 4 * * 0`, `run_at_startup=True`) | Syncs EhTag translations from CDN (`cdn.jsdelivr.net`); runs immediately on first boot, then weekly; delegates to `services/ehtag_importer.py`; registered in `scheduled_tasks.py` TASK_DEFS |
| `log_cleanup_job` | ARQ cron (`30 3 * * *`) | Trim `system_logs` Redis list: remove entries older than `log_retention_days`, cap at `log_max_entries` |
| `disk_monitor_job` | ARQ cron (*/5, `run_at_startup`) | Check disk space via `shutil.disk_usage("/data")`; sets `system:disk_low` Redis key (TTL 600s) with free GB value when below `disk_min_free_gb`, deletes key when recovered; emits `SYSTEM_DISK_LOW` event |
| `adaptive_persist_job` | ARQ cron (*/5) | Flush dirty adaptive states from Redis to DB. SPOP up to 200 items, batch upsert in single session, re-add failed items. Registered in `worker/__init__.py` |

#### Standard Pipeline

Two paths depending on the download engine used:

**gallery-dl path** (subprocess via `GalleryDlPlugin`):
```
download_job (gallery-dl subprocess) → [ProgressiveImporter — inline during download]
  ├── on_file() called per media file: store_blob → Image record → symlink → thumbnail_job
  ├── finalize(): update pages count + download_status, cleanup temp dir
  └── tag_job (if enabled, after finalize)
```

**Native plugin path** (e.g., EH, Pixiv):
```
download_job → import_job → thumbnail_job
                           └→ tag_job (if enabled)
```

#### Progressive Import (`worker/progressive.py`)

`ProgressiveImporter` runs **inline inside `download_job`** for gallery-dl downloads, making images available in the library as they arrive rather than waiting for the full download to complete.

| Method | Behaviour |
|--------|-----------|
| `on_file(path, metadata)` | Called per media file from `_read_stdout`; creates gallery on first file (from metadata JSON or URL fallback), then store_blob → Image record → symlink → enqueue thumbnail |
| `finalize()` | Updates `pages` count and `download_status → done`; removes temp dir |
| `abort()` | Marks gallery as `partial` and preserves already-imported files (called on error) |
| `cleanup()` | Fully deletes gallery, decrements blob ref counts, removes symlinks and thumbnails (called on cancel) |

Gallery is created on the **first media file** encountered. If a metadata JSON is present at that point it provides title/artist/tags; otherwise a URL-derived fallback title is used and metadata is patched in `finalize()`.

#### Download Status Transitions

```
queued → running → done
                 → partial    (some files imported but error or corrupt pages detected)
                 → failed     (0 files downloaded or unrecoverable error)
                 → cancelled  (user-initiated via cancel API)
```

#### Pause / Resume 機制

`download_job` 使用 Redis soft-pause 統一暫停機制（所有下載引擎共用）：

- Pause：`PATCH /api/download/jobs/{id}` (`action=pause`) → API 寫入 Redis key `download:pause:{job_id}`（24h TTL）
- Worker 在每張新圖**開始前** poll 該 key；若存在則 `sleep 0.5s` 等待
- 正在傳輸中的圖**不中斷**，只阻擋尚未開始的新圖
- Resume：`PATCH /api/download/jobs/{id}` (`action=resume`) → API 刪除 key → worker 繼續

> 注意：gallery-dl subprocess 模式的 pause 是「協作式」暫停 — gallery-dl 進程本身不會被暫停，但 worker 不會啟動新的下載任務直到 resume。

#### Cancel 機制

- Cancel: `POST /api/download/jobs/{id}/cancel` → sends SIGTERM to the gallery-dl subprocess PID and writes Redis key `download:cancel:{job_id}`
- `_read_stdout` checks the cancel key on **every stdout line**; when triggered it kills the process and breaks out of the read loop
- A post-download cancel guard re-checks the key after the subprocess exits to prevent a race condition where finalization would overwrite the cancelled status
- Cancel triggers `ProgressiveImporter.cleanup()` (full gallery deletion), **not** `abort()` (partial preservation)

#### Worker Startup Cleanup (`__init__.py` → `startup()`)

On startup, the worker performs crash-recovery housekeeping with configurable strategies (admin-settable via `GET/PATCH /api/settings/recovery-strategy`, stored in Redis keys `setting:recovery_running` and `setting:recovery_paused`):

1. **Orphaned gallery statuses** — resets `downloading` galleries back to `partial` (always runs, regardless of strategy)
2. **Stale running jobs** — strategy `auto_retry` (default): re-enqueue with `retry_count++`; strategy `mark_failed`: set `status=failed`
3. **Stale queued jobs** — re-enqueues `queued` jobs that survived a crash (new ARQ task via `enqueue_download_job`)
4. **Stale paused jobs** — strategy `keep_paused` (default): re-enqueue for pause gate; strategy `auto_retry`: delete pause key + re-enqueue as retry; strategy `mark_failed`: delete pause key + mark failed
5. **Subscription group reset** — marks `running` groups as `idle`
6. **Emit `SYSTEM_WORKER_RECOVERED`** — event with strategy names + recovery counts (running_retried, running_failed, paused_kept, paused_retried, paused_failed, queued_requeued)

#### Resume Re-enqueue (`routers/download.py`)

When resuming a paused job, the router checks if the ARQ coroutine is still alive (`arq:result:{job_id}` key). If dead, it re-enqueues as a new ARQ job with incremented `retry_count` rather than just flipping the status flag.

#### Library Watcher

`core/watcher.LibraryWatcher` uses `watchdog` (or polling when `watcher_use_polling=true`). On file events it enqueues `rescan_by_path_job`. Status persisted in Redis key `watcher:status`.

---

### Plugin System

Base module: `backend/plugins/`

#### Abstract Base Classes (`plugins/base.py`)

| ABC | Methods | Purpose |
|-----|---------|---------|
| `SourcePlugin` | `can_handle(url)`, `download(...)`, `parse_metadata(dest_dir)` | Downloads galleries |
| `BrowsePlugin` | `browse_schema()`, `search(params, creds)`, `proxy_image(url, creds)` | Browse/search remote sources |
| `TaggerPlugin` | `tag_images(image_paths)` | AI/ML image tagging |

#### Protocol Interfaces (`plugins/base.py`)

| Protocol | Methods | Purpose |
|----------|---------|---------|
| `HasMeta` | `meta: PluginMeta` | Base protocol — all plugins have metadata |
| `Downloadable` | `can_handle(url)`, `download(...)`, `resolve_output_dir(...)`, `requires_credentials()` | Downloads galleries |
| `Browsable` | `get_browse_router()` | Provides a FastAPI router for browse endpoints |
| `Parseable` | `parse_import(dest_dir, raw_meta)` | Parses downloaded directory into GalleryImportData |
| `Subscribable` | `check_new_works(artist_id, last_known, creds)` | Duck-type convention (no formal Protocol class); implemented directly in ehentai/pixiv source plugins |
| `CredentialProvider` | `credential_flows()`, `verify_credential(creds)` | Declares credential auth flows and verification |
| `Taggable` | `tag_images(image_paths)` | AI/ML image tagging |

#### Pydantic Models (`plugins/models.py`)

| Model | Purpose |
|-------|---------|
| `PluginMeta` | Plugin identity: `source_id`, `name`, `version`, `url_patterns`, `credential_schema`, `concurrency` |
| `FieldDef` | Credential form field descriptor |
| `GalleryMetadata` | Parsed gallery metadata from a download |
| `DownloadResult` | Result from `SourcePlugin.download()` |
| `SearchResult` | Paginated browse results |
| `BrowseSchema` | Describes search fields and capabilities |
| `TagResult` | Per-image AI tagging output |
| `CredentialFlow` | Credential auth flow descriptor (fields/oauth/login) |
| `OAuthConfig` | OAuth endpoint configuration |
| `CredentialStatus` | Credential verification result |
| `GalleryImportData` | Structured gallery import data from parser |
| `NewWork` | New work notification from subscription check |
| `SiteInfo` | Site domain/name/category info for site index |

#### Registry (`plugins/registry.py`)

Singleton `plugin_registry` (`PluginRegistry`). Maintains a site index (domain→SiteInfo) for URL detection, routes downloads to matching plugins with `gallery_dl` as fallback. Also tracks capability maps: `_browsable`, `_downloadable`, `_parseable`, `_subscribable`, `_credential_providers`, `_taggable`. Browse routers are dynamically mounted at startup via `get_browse_routers()`.

#### Built-in Plugins

| Plugin | source_id | Interfaces | Description |
|--------|-----------|------------|-------------|
| `ehentai/source.py` | `ehentai` | Downloadable, Parseable, Subscribable | Native EH download via `EhClient` + subscription checks |
| `ehentai/browse.py` | `ehentai` | BrowsePlugin, Browsable, CredentialProvider | EH browse endpoints + credential flows |
| `pixiv/source.py` | `pixiv` | Downloadable, Parseable, Subscribable | Pixiv artwork download + subscription checks |
| `pixiv/_browse.py` | `pixiv` | BrowsePlugin, Browsable, CredentialProvider | Pixiv browse endpoints + credential flows |
| `gallery_dl/source.py` | `gallery_dl` | SourcePlugin, CredentialProvider | gallery-dl subprocess fallback (any URL) + generic cookie flows; site config driven by `_sites.py` unified registry. `on_file` callback and `options` are passed as per-call parameters (not stored as instance state) to prevent pollution across concurrent downloads. |


#### Gallery-DL Site Registry (`plugins/builtin/gallery_dl/_sites.py`)

Single source of truth for all 30 gallery-dl supported sites. Each `GdlSiteConfig` entry defines:

| Field | Purpose | Example |
|-------|---------|---------|
| `domain`, `source_id`, `name`, `category` | Site identity (generates `SiteInfo` list) | `twitter.com`, `twitter`, `Twitter/X`, `social` |
| `image_order`, `cover_page`, `title_fields` | Per-source display config; `title_fields` supports dot notation for nested metadata access (e.g., `"author.name"`) | `desc`, `last`, `("username",)` for Twitter |
| `artist_from` | Artist extraction strategy (`uploader`/`tag`/`twitter_author`/`none`) | `tag` for booru sources |
| `subscribe_id_key`, `subscribe_url_tpl` | Subscription support (replaces `_subscribe.py` `SITE_CONFIG`) | `tweet_id`, `https://x.com/{}/media` |
| `extractor` | gallery-dl extractor name override (replaces `_source_to_extractor()` mapping) | `sankakucomplex` for sankaku |

Consumers: `source.py` (site list + extractor mapping), `_subscribe.py` (subscription config), `_metadata.py` (artist/title extraction), `importer.py` (artist fallback), `plugins/__init__.py` (proxy registration), `core/site_config.py` (defaults layer for merge).

Lookup helpers: `get_site_config(source_id)`, `get_site_by_domain(domain)`.

Download tuning fields (`retries`, `http_timeout`, `sleep_request`, `inactivity_timeout`) serve as the **defaults layer** for `SiteConfigService`. DB overrides and adaptive values take precedence. `concurrency` defaults to 2 (not in `GdlSiteConfig`).

#### Per-Source Display Config (`core/source_display.py`)

Thin wrapper over `_sites.py` that exposes `get_display_config(source) → SourceDisplayConfig` for routers. Returns `image_order` (`asc`/`desc`) and `cover_page` (`first`/`last`). Non-gallery-dl sources (ehentai, pixiv, local) get default config (`asc`, `first`).

Used by: `routers/library.py` (cover selection, image ordering, `display_order` response field), `routers/collections.py` (cover selection), `routers/opds.py` (cover selection, page ordering).

---

### Core Modules (`backend/core/`)

| File | Description |
|------|-------------|
| `auth.py` | Session auth (`require_auth`), RBAC (`require_role`), gallery access filter |
| `audit.py` | `log_audit()` — fire-and-forget audit trail writer (raw SQL insert to `audit_logs`) |
| `compat.py` | Python 3.14 asyncio compatibility patch (`get_event_loop()` fallback) |
| `config.py` | Pydantic `BaseSettings` — all env-based configuration (incl. `disk_min_free_gb` default 2.0 GB) |
| `csrf.py` | CSRF token middleware (`CSRFMiddleware`) |
| `database.py` | SQLAlchemy async engine + `AsyncSessionLocal` factory |
| `errors.py` | Custom exception classes |
| `events.py` | Unified EventBus — structured event emit via Redis Pub/Sub + recent event list (see EventBus section below) |
| `rate_limit.py` | Rate limiting middleware (`RateLimitMiddleware`) |
| `redis_client.py` | Redis connection pool management; `publish_job_event()` bridge from legacy download events to EventBus |
| `adaptive.py` | `AdaptiveEngine` singleton — automatic rate limiting feedback loop. Detects 429/503/403/timeout signals from gallery-dl stderr, adjusts `sleep_multiplier` and `http_timeout_add` via Redis Lua script. Content validation (HTML/empty detection) feeds back. Success recovery at %20 (sm decay) and %100 (hta decrement). Cron persists dirty states to DB every 5 min. `AdaptiveState.from_dict()` factory, `parse_adaptive_signal()` regex parser |
| `site_config.py` | `SiteConfigService` singleton — per-site download tuning (retries, timeout, sleep, concurrency, inactivity). In-memory cache (30s TTL) + Redis Pub/Sub cross-container invalidation. Merge: DB override > DB adaptive > `_sites.py` defaults. `JYZROX_FIELDS` canonical field set. `get_params_with_row()` / `get_all_with_rows()` for single-query param+row retrieval |
| `probe.py` | M2 Probe Engine — SSRF-protected `gallery-dl --dump-json` analysis. 5-layer defense (scheme allowlist, DNS private-IP reject, execution limits, 2 MB output cap, 60s timeout). Three-step analysis: field diffing (gallery vs page level), type fingerprinting (7 types), role scoring (weighted mapping suggestions). `probe_url()` → `ProbeResult` |
| `source_display.py` | Per-source display config wrapper over `_sites.py` |
| `utils.py` | General utilities — delegates `detect_source` / `get_supported_sites` to plugin_registry |
| `watcher.py` | `LibraryWatcher` — filesystem monitor (watchdog / polling) |
| `log_handler.py` | `RedisLogHandler` (Python logging handler → Redis), `install_log_handler()` with `extra_loggers` support for framework loggers |

---

### Services (`backend/services/`)

| File | Description |
|------|-------------|
| `cache.py` | Caching utilities |
| `cas.py` | Content-Addressable Storage — blob store, hash, symlink |
| `credential.py` | Credential encryption/decryption (AES-256-GCM) |
| `eh_client.py` | E-Hentai HTTP client — gallery metadata, image lists, favorites |
| `eh_downloader.py` | E-Hentai concurrent image downloader |
| `ehtag_importer.py` | EhTag translation CDN importer — fetches `db.text.json` from jsdelivr, upserts `tag_translations` |
| `pixiv_client.py` | Pixiv API client — OAuth, search, illust, user, bookmarks |
| `pixiv_downloader.py` | Pixiv concurrent image downloader |

---

### EventBus (`core/events.py`)

Unified structured event system. All events are advisory (never block user-facing operations).

#### Architecture

- **Publish:** Redis Pub/Sub pipeline — each event published to `events:{type}` + `events:all` channels, and `LPUSH`ed to `events:recent` list (max 200, amortized `LTRIM` every 50 emits)
- **Subscribe:** WebSocket relay at `/api/ws/ws` subscribes to `events:all`, filters by user role, and translates to legacy WS message format
- **Query:** `GET /api/system/events?limit=50` (admin only) reads from `events:recent`
- **Fire-and-forget:** All emitters use `emit_safe()` which swallows exceptions

#### Event Data Structure

```python
@dataclass
class Event:
    event_type: EventType      # Enum value (e.g., "gallery.updated")
    timestamp: str             # ISO8601 UTC (auto-generated)
    actor_user_id: int | None  # User who triggered (None = system)
    resource_type: str | None  # "gallery", "download_job", "subscription", etc.
    resource_id: int|str|None  # Gallery ID, job UUID, etc.
    data: dict[str, Any]       # Extra context (progress, error, count, etc.)
```

#### EventType Enum (36 types)

| Domain | Types |
|--------|-------|
| Download | `DOWNLOAD_ENQUEUED`, `DOWNLOAD_STARTED`, `DOWNLOAD_PROGRESS`, `DOWNLOAD_COMPLETED`, `DOWNLOAD_FAILED`, `DOWNLOAD_CANCELLED`, `DOWNLOAD_PAUSED`, `SEMAPHORE_CHANGED` |
| Gallery | `GALLERY_UPDATED`, `GALLERY_DELETED`, `GALLERY_RESTORED`, `GALLERY_BATCH_UPDATED`, `GALLERY_DISCOVERED`, `GALLERY_TAGGED` |
| Import | `IMPORT_COMPLETED`, `IMPORT_FAILED` |
| Subscription | `SUBSCRIPTION_CREATED`, `SUBSCRIPTION_DELETED`, `SUBSCRIPTION_CHECKED`, `SUBSCRIPTION_GROUP_UPDATED`, `SUBSCRIPTION_GROUP_COMPLETED` |
| Collection | `COLLECTION_UPDATED` |
| Tag | `TAGS_UPDATED` |
| Dedup | `DEDUP_SCAN_STARTED`, `DEDUP_SCAN_COMPLETED`, `DEDUP_PAIR_RESOLVED` |
| Thumbnail | `THUMBNAILS_GENERATED` |
| System | `TRASH_CLEANED`, `RESCAN_COMPLETED`, `RETRY_PROCESSED`, `EHTAG_SYNC_COMPLETED`, `RECONCILIATION_COMPLETED`, `SYSTEM_ALERT`, `SYSTEM_DISK_LOW`, `SYSTEM_GDL_UPGRADED`, `SYSTEM_WORKER_RECOVERED`, `LOG_LEVEL_CHANGED` |
| Adaptive | `ADAPTIVE_BLOCKED` |

#### Emission Points

**Routers** (inline `from core.events import EventType, emit_safe`):
- `collections.py` — `COLLECTION_UPDATED` (create/add/remove/delete)
- `download.py` — `DOWNLOAD_ENQUEUED`, `DOWNLOAD_CANCELLED`
- `library.py` — `GALLERY_UPDATED`, `GALLERY_RESTORED`, `GALLERY_DELETED`
- `subscriptions.py` — `SUBSCRIPTION_CREATED`, `SUBSCRIPTION_DELETED`
- `subscription_groups.py` — `SUBSCRIPTION_GROUP_UPDATED`, `SUBSCRIPTION_GROUP_COMPLETED`
- `dedup.py` — `DEDUP_PAIR_RESOLVED`, `DEDUP_SCAN_STARTED`
- `tag.py` — `TAGS_UPDATED`

**Workers** (emit at end of job, after DB commit):
- `importer.py` — `IMPORT_COMPLETED`
- `scan.py` — `RESCAN_COMPLETED`, `GALLERY_DISCOVERED`
- `tagging.py` — `GALLERY_TAGGED`
- `thumbnail.py` — `THUMBNAILS_GENERATED`
- `dedup_scan.py` — `DEDUP_SCAN_COMPLETED`
- `reconciliation.py` — `RECONCILIATION_COMPLETED`
- `retry.py` — `RETRY_PROCESSED`
- `trash.py` — `TRASH_CLEANED`
- `ehtag_sync.py` — `EHTAG_SYNC_COMPLETED`
- `subscription_group.py` — `SUBSCRIPTION_GROUP_COMPLETED`
- `download.py` — `SYSTEM_DISK_LOW` (pre-flight check, syscall fallback only)
- `__init__.py` — `SYSTEM_DISK_LOW` (disk_monitor_job cron, every 5 min), `SYSTEM_WORKER_RECOVERED` (startup recovery)
- `source.py` (`_on_file_with_validation`) — `ADAPTIVE_BLOCKED` (3+ HTML responses in same download)
- `redis_client.py` — `SEMAPHORE_CHANGED` (on semaphore acquire/release)

**Legacy bridge** (`core/redis_client.publish_job_event`):
- Translates `{"type": "job_update", ...}` dicts to `DOWNLOAD_*` EventBus events
- Translates `{"type": "subscription_checked", ...}` to `SUBSCRIPTION_CHECKED`

#### WebSocket Relay (`routers/ws.py`)

3 concurrent tasks per connection:
1. **PubSub listener** — subscribes to `events:all`, filters by role (admin sees all, others see own events or broadcasts), translates to legacy WS message format
2. **Ping loop** — sends `ping` + system alerts every 2s
3. **WS receiver** — listens for client disconnect

#### Redis Keys

| Key/Channel | Type | Purpose |
|-------------|------|---------|
| `events:recent` | List | Up to 200 most recent events (newest at head) |
| `events:{event_type}` | Pub/Sub | Per-type channel (e.g., `events:gallery.updated`) |
| `events:all` | Pub/Sub | All events broadcast |

---

### Configuration (`core/config.py`)

All fields read from `.env` via Pydantic `BaseSettings`.

#### Database & Cache

| Field | Default | Description |
|-------|---------|-------------|
| `database_url` | — | PostgreSQL async DSN (required) |
| `redis_url` | `redis://redis:6379` | Redis connection URL |

#### Security

| Field | Default | Description |
|-------|---------|-------------|
| `credential_encrypt_key` | — | AES-256-GCM key for credentials table (required) |
| `cors_origin` | `""` | Allowed CORS origins (comma-separated); empty = same-origin only |
| `cookie_secure` | `true` | Set `false` for local HTTP dev |
| `trusted_proxies` | `172.16.0.0/12,10.0.0.0/8,192.168.0.0/16` | CIDRs for real-IP extraction |

#### Rate Limiting

| Field | Default | Description |
|-------|---------|-------------|
| `rate_limit_enabled` | `true` | Enable FastAPI rate limiter |
| `rate_limit_login` | `5` | Max login attempts per window |
| `rate_limit_window` | `300` | Window in seconds (5 min) |

#### Feature Toggles

| Field | Default | Description |
|-------|---------|-------------|
| `csrf_enabled` | `true` | CSRF token validation |
| `opds_enabled` | `true` | OPDS catalog endpoint |
| `external_api_enabled` | `true` | External API (`/api/external/v1`) |
| `download_eh_enabled` | `true` | EH download feature |
| `download_pixiv_enabled` | `true` | Pixiv download feature |
| `download_gallery_dl_enabled` | `true` | gallery-dl fallback feature |

#### Feature Toggles (Redis-backed)

> Additional feature flags stored in Redis, dynamically toggled via `/api/settings`.

| Key | Default | Description |
|-----|---------|-------------|
| `setting:tag_translation_enabled` | `true` | Enable tag translation display (OpenCC zh-TW conversion) |

#### Dedup Settings (Redis-backed)

> Dedup 設定不在 `core/config.py`，而是存於 Redis（`setting:dedup_*`），可在 `/api/settings` 動態修改。

| Key | Default | Description |
|-----|---------|-------------|
| `setting:dedup_phash_enabled` | `false` | Enable Tier 1 pHash scan |
| `setting:dedup_phash_threshold` | `10` | Hamming distance threshold (0–64) |
| `setting:dedup_heuristic_enabled` | `false` | Enable Tier 2 heuristic classification |
| `setting:dedup_opencv_enabled` | `false` | Enable Tier 3 OpenCV pixel-diff |
| `setting:dedup_opencv_threshold` | `0.85` | OpenCV similarity threshold |

#### Retry Settings (Redis-backed)

> 重試設定存於 Redis（`setting:retry_*`），可在 `/api/settings` 動態修改。

| Key | Default | Description |
|-----|---------|-------------|
| `setting:retry_enabled` | `true` | Enable automatic retry of failed/partial downloads |
| `setting:retry_max_retries` | `3` | Maximum retry attempts per job |
| `setting:retry_base_delay_minutes` | `5` | Base delay for exponential backoff (minutes) |

#### E-Hentai Limits

| Field | Default | Description |
|-------|---------|-------------|
| `eh_max_concurrency` | `2` | EH image proxy semaphore limit |
| `eh_request_timeout` | `30` | HTTP request timeout (seconds) |
| `eh_acquire_timeout` | `60` | Semaphore acquire timeout (seconds) |
| `eh_use_ex` | `false` | Use ExHentai instead of E-Hentai |
| `eh_download_concurrency` | `3` | Parallel images per gallery download |
| `eh_download_max_retries` | `3` | NL retries per image |

#### AI Tagging

| Field | Default | Description |
|-------|---------|-------------|
| `tag_model_enabled` | `false` | Enable WD14 AI tagger |
| `tag_model_name` | `SmilingWolf/wd-swinv2-tagger-v3` | HuggingFace model ID |
| `tag_general_threshold` | `0.35` | General tag confidence threshold |
| `tag_character_threshold` | `0.85` | Character tag confidence threshold |
| `tagger_url` | `http://tagger:8100` | WD14 tagger microservice URL |
| `tagger_timeout` | `30` | Tagger HTTP request timeout (seconds) |

#### Storage Paths

| Field | Default | Description |
|-------|---------|-------------|
| `data_gallery_path` | `/data/gallery` | Gallery download root |
| `data_thumbs_path` | `/data/thumbs` | WebP thumbnail root |
| `data_training_path` | `/data/training` | Kohya export root |
| `data_avatars_path` | `/data/avatars` | User avatar upload root |
| `data_cas_path` | `/data/cas` | Content-Addressable Storage root |
| `data_library_path` | `/data/library` | Library symlink root |
| `data_archive_path` | `/data/archive` | Archived gallery data root |
| `gallery_dl_config` | `/app/config/gallery-dl.json` | gallery-dl config file path |

#### Pixiv OAuth

| Field | Default | Description |
|-------|---------|-------------|
| `pixiv_client_id` | `MOBrBDS8blbauoSck0ZfDbtuzpyT` | Android app client ID |
| `pixiv_client_secret` | `lsACyCD94FhDUtGTXi3QzcFE2uU1hqtDaKeqrdwj` | Android app client secret |
| `pixiv_max_concurrency` | `4` | Max concurrent Pixiv API requests |
| `pixiv_image_concurrency` | `6` | Max concurrent Pixiv image downloads |
| `pixiv_request_timeout` | `30` | Request timeout (seconds) |

#### Library Management

| Field | Default | Description |
|-------|---------|-------------|
| `library_monitor_enabled` | `true` | Enable file system watcher on startup |
| `library_scan_interval_hours` | `24` | Scheduled scan interval |
| `extra_library_paths` | `""` | Comma-separated extra library paths (env-only) |
| `library_base_path` | `/mnt` | Default root for user-mounted external media |
| `watcher_use_polling` | `false` | Use polling instead of inotify |
| `watcher_polling_interval` | `60` | Polling interval (seconds) |

> `data_gallery_path` is the download engine's internal workspace; it is NOT added to library paths automatically.

---

### Authentication

#### Session Auth (Cookie)

- Cookie name: `vault_session = {user_id}:{token}` (httpOnly, SameSite=Strict)
- Redis key: `session:{user_id}:{token}` (TTL 30 days)
- FastAPI dependency: `from core.auth import require_auth` — add `_: dict = Depends(require_auth)` to every protected endpoint
- CSRF protection: `csrf_token` cookie; all mutating requests must send `X-CSRF-Token` header

### Role-Based Access Control

三級階層式角色（`core/auth.py`）：

| Role | Level | Scope |
|------|-------|-------|
| `admin` | 3 | System config, user management, credentials, scheduled tasks, dedup |
| `member` | 2 | Download, import/export, subscriptions, gallery edits |
| `viewer` | 1 | Browse, search, history, collections (read-only) |

- `require_auth()` → `{"user_id": int, "role": str}` — any authenticated user
- `require_role("admin")` → factory returning dependency that checks `role >= admin`
- Role stored in Redis session JSON, read on every request (no DB query)
- User management: `POST/PATCH/DELETE /api/users` (admin only)

#### OPDS Basic Auth

- Endpoint: `/opds/`
- Dependency: `require_opds_auth` in `routers/opds.py`
- Validates HTTP Basic Auth credentials directly against the `users` table
- Nginx does NOT apply `auth_request` to `/opds/` — it would break OPDS clients

#### External API Token Auth

- Endpoint: `/api/external/v1/`
- Header: `X-API-Token: <token>`
- Tokens stored (hashed) in `api_tokens` table
- Managed via `/api/settings/tokens`

---

## Frontend (Next.js 16 PWA)

Source root: `pwa/src/`

### Page Routes

| Route | File | Description |
|-------|------|-------------|
| `/` | `app/page.tsx` | Dashboard — recent galleries + active downloads |
| `/login` | `app/login/page.tsx` | Username + password login form |
| `/setup` | `app/setup/page.tsx` | First-run admin account creation |
| `/e-hentai` | `app/e-hentai/page.tsx` | E-Hentai search + quick download |
| `/e-hentai/[gid]/[token]` | `app/e-hentai/[gid]/[token]/page.tsx` | EH gallery detail page |
| `/e-hentai/read/[gid]/[token]` | `app/e-hentai/read/[gid]/[token]/page.tsx` | EH online reader (proxy mode) |
| `/library` | `app/library/page.tsx` | Local gallery grid with tag/rating/source filters |
| `/library/[source]/[sourceId]` | `app/library/[source]/[sourceId]/page.tsx` | Gallery detail — tags, thumbnails, read/favorite |
| `/reading-list` | `app/reading-list/page.tsx` | Reading list (read later) — gallery list with remove button |
| `/reader/[source]/[sourceId]` | `app/reader/[source]/[sourceId]/page.tsx` | Full local reader (single/webtoon/double-page) |
| `/queue` | `app/queue/page.tsx` | Download queue management |
| `/tags` | `app/tags/page.tsx` | Tag listing + alias/implication management |
| `/settings` | `app/settings/page.tsx` | System settings and feature flags |
| `/credentials` | `app/credentials/page.tsx` | Credential management (EH cookies, Pixiv token) |
| `/import` | `app/import/page.tsx` | Local import wizard + library path management |
| `/export` | `app/export/page.tsx` | Kohya export UI |
| `/history` | `app/history/page.tsx` | Browse history |
| `/artists` | `app/artists/page.tsx` | Artist listing + follow management |
| `/plugins` | `app/plugins/page.tsx` | Plugin listing + credential status |
| `/pixiv` | `app/pixiv/page.tsx` | Pixiv search/browse |
| `/pixiv/following` | `app/pixiv/following/page.tsx` | Pixiv following feed |
| `/pixiv/user/[id]` | `app/pixiv/user/[id]/page.tsx` | Pixiv user profile |
| `/pixiv/illust/[id]` | `app/pixiv/illust/[id]/page.tsx` | Pixiv illust detail |
| `/subscriptions` | `app/subscriptions/page.tsx` | Subscription management with group-based scheduling — collapsible group cards, run/pause/resume, bulk move between groups |
| `/explorer` | `app/explorer/page.tsx` | File explorer for local library paths |
| `/share-target` | `app/share-target/page.tsx` | PWA Web Share Target handler |
| `/scheduled-tasks` | `app/scheduled-tasks/page.tsx` | Scheduled task management — list, enable/disable, cron edit, manual run |
| `/dedup` | `app/dedup/page.tsx` | Dedup dashboard — tier settings, scan trigger, review list with keep/whitelist/skip actions |
| `/forbidden` | `app/forbidden/page.tsx` | 403 access denied page |
| `/admin/users` | `app/admin/users/page.tsx` | User management (admin only) |
| `/admin/sites` | `app/admin/sites/page.tsx` | Site config builder (admin only) — category-grouped site list, slide-out editor (download settings + field mapping), probe dialog with auto-detection |
| `/admin/dashboard` | `app/admin/dashboard/page.tsx` | Live download dashboard (admin only) — global status bar, per-site semaphore/speed/delay table, active jobs with STALLING detection, queued jobs with wait reasons |
| `/artists/[artistId]` | `app/artists/[artistId]/page.tsx` | Individual artist detail page |
| `/reader/artist/[artistId]` | `app/reader/artist/[artistId]/page.tsx` | Artist gallery reader |
| `/reader/pixiv/[id]` | `app/reader/pixiv/[id]/page.tsx` | Pixiv online reader |
| `/images` | `app/images/page.tsx` | Image Browser — justified grid layout, tag filtering, cursor-based pagination |
| `/trash` | `app/trash/page.tsx` | Trash — soft-deleted gallery list with restore, permanent delete, empty trash |
| `/logs` | `app/logs/page.tsx` | Application log viewer (admin only) — level/source filters, keyword search, real-time streaming |

---

### Key Components

| Component | File | Description |
|-----------|------|-------------|
| `Reader` | `components/Reader/index.tsx` | Full reader — single/webtoon/double-page modes, touch + keyboard nav |
| `VideoPlayer` | `components/Reader/VideoPlayer.tsx` | `<video>` wrapper for `.mp4`/`.webm` pages inside Reader |
| `VirtualGrid` | `components/VirtualGrid.tsx` | Virtualized gallery grid for large collections |
| `GalleryCard` | `components/GalleryCard.tsx` | Gallery thumbnail card with rating and status |
| `TagBadge` | `components/TagBadge.tsx` | Clickable tag pill with namespace colour |
| `TagInput` | `components/TagInput.tsx` | Multi-tag input with autocomplete |
| `TagAutocomplete` | `components/TagAutocomplete.tsx` | Autocomplete dropdown for tag search |
| `ErrorBoundary` | `components/ErrorBoundary.tsx` | React error boundary wrapper |
| `LayoutShell` | `components/LayoutShell.tsx` | App shell with sidebar + mobile nav |
| `CredentialBanner` | `components/CredentialBanner.tsx` | Banner alert when source credentials are missing or invalid |
| `Sidebar` | `components/Sidebar.tsx` | Desktop navigation sidebar |
| `MobileNav` | `components/MobileNav.tsx` | Bottom navigation for mobile |
| `NavBar` | `components/NavBar.tsx` | Top navigation bar |
| `Pagination` | `components/Pagination.tsx` | Page cursor-based pagination control |
| `RatingStars` | `components/RatingStars.tsx` | 5-star rating widget |
| `DownloadStatusBadge` | `components/DownloadStatusBadge.tsx` | Gallery download status indicator |
| `JobStatusBadge` | `components/JobStatusBadge.tsx` | ARQ job status badge |
| `EmptyState` | `components/EmptyState.tsx` | Empty list placeholder |
| `LoadingSpinner` | `components/LoadingSpinner.tsx` | Loading indicator |
| `SWUpdatePrompt` | `components/SWUpdatePrompt.tsx` | PWA service worker update prompt |
| `LocaleProvider` | `components/LocaleProvider.tsx` | i18n locale context provider |
| `ThemeProvider` | `components/ThemeProvider.tsx` | Dark/light theme context |
| `TaskList` | `components/ScheduledTasks/TaskList.tsx` | Scheduled task list container |
| `TaskCard` | `components/ScheduledTasks/TaskCard.tsx` | Individual task card — cron inline edit, enable toggle, run button |
| `StatusBadge` | `components/ScheduledTasks/StatusBadge.tsx` | Task status badge (running/success/failed) |
| `ReviewList` | `components/Dedup/ReviewList.tsx` | Dedup review list with filtering and pagination |
| `RelationshipCard` | `components/Dedup/RelationshipCard.tsx` | Side-by-side pair display with keep/whitelist/skip actions |
| `DedupSettingsCard` | `components/Dedup/DedupSettingsCard.tsx` | Tier enable toggles + threshold sliders |
| `DedupTierCard` | `components/Dedup/DedupTierCard.tsx` | Per-tier status and config |
| `ImageModal` | `components/Dedup/ImageModal.tsx` | Full-size image preview modal for dedup review |
| `BackButton` | `components/BackButton.tsx` | Navigation back button |
| `BottomTabBar` | `components/BottomTabBar.tsx` | Bottom tab navigation for mobile |
| `ContextMenu` | `components/ContextMenu.tsx` | Portal-based context menu with icon + label items |
| `FastScroller` | `components/FastScroller.tsx` | Drag-to-scroll thumb for virtualized lists |
| `FloatingActions` | `components/FloatingActions.tsx` | Floating action buttons (scroll-to-top, etc.) |
| `Skeleton` | `components/Skeleton.tsx` | Skeleton loading placeholders (`SkeletonCard`, etc.) |
| `ImageContextMenu` | `components/Reader/ImageContextMenu.tsx` | Reader image context menu (download, copy, share) |
| `JustifiedGrid` | `components/JustifiedGrid.tsx` | Generic justified-layout grid with `@tanstack/react-virtual` window virtualisation; accepts `getAspectRatio` + `renderItem` callbacks; fires `onLoadMore` when last row is visible; uses `justified-layout` for geometry calculation |
| `GalleryListCard` | `components/GalleryListCard.tsx` | List-view gallery card (compact row layout with actions) |
| `BottomTabConfig` | `components/BottomTabConfig.tsx` | Bottom tab bar customisation — drag-to-reorder, show/hide tabs |
| `DashboardLinksConfig` | `components/DashboardLinksConfig.tsx` | Dashboard quick-link customisation — drag-to-reorder, show/hide links |
| `TimelineScrubber` | `components/TimelineScrubber.tsx` | Drag-to-scrub timeline control for Image Browser date navigation |

---

### Hooks

All hooks in `pwa/src/hooks/`.

| Hook | File | Description |
|------|------|-------------|
| `useAuth` | `useAuth.ts` | `login(username, password)`, `logout()`, session state |
| `useProfile` | `useProfile.ts` | User profile data (SWR) |
| `useGalleries` | `useGalleries.ts` | `useLibraryGalleries`, `useLibraryGallery`, `useGalleryImages` (SWR) |
| `useDownloadQueue` | `useDownloadQueue.ts` | `useDownloadJobs` (3s refresh / WS real-time), `useEnqueueDownload`, `useCancelJob`, `useRetryJob`, `usePauseJob` |
| `useDashboard` | `useDashboard.ts` | 2s throttled WS revalidation, 5s poll fallback |
| `useImport` | `useImport.ts` | Import flow state and progress |
| `useArtists` | `useArtists.ts` | Followed artists listing and actions |
| `useTagTranslations` | `useTagTranslations.ts` | Tag translation lookup (SWR) |
| `useCollections` | `useCollections.ts` | Collection CRUD and gallery management (SWR) |
| `useScheduledTasks` | `useScheduledTasks.ts` | Scheduled task listing, enable/disable, manual run |
| `useSubscriptions` | `useSubscriptions.ts` | Subscription CRUD and manual check trigger |
| `useDedup` | `useDedup.ts` | Dedup stats, review list, keep/whitelist/skip actions, scan control |
| `useScrollRestore` | `useScrollRestore.ts` | Scroll position restoration |
| `useGridKeyboard` | `useGridKeyboard.ts` | Keyboard navigation in gallery grids |
| `useSwipeBack` | `useSwipeBack.ts` | Swipe back gesture detection |
| `useLibraryFilters` | `useLibraryFilters.ts` | Library filter state management with URL search params sync |
| `useLongPress` | `useLongPress.ts` | Long-press gesture detection (configurable threshold) |
| `useThumbhash` | `useThumbhash.ts` | Decode base64 thumbhash to placeholder image via Web Worker |
| `useImageBrowser` | `useImageBrowser.ts` | SWR infinite hook for `GET /api/library/images`; cursor-based; accepts `tags`, `exclude_tags`, `sort`, `gallery_id`, `limit`; exposes `images`, `loadMore`, `isReachingEnd` |
| `useIllustActions` | `useIllustActions.ts` | Pixiv illust actions — download, bookmark, share |
| `useNavCounts` | `useNavCounts.ts` | Navigation badge counts (library total, queue active, etc.) via SWR |
| `usePullToRefresh` | `usePullToRefresh.ts` | Pull-to-refresh gesture detection for mobile |
| `useTimeRange` | `useTimeRange.ts` | Image time range + timeline percentiles queries for Image Browser scrubber |
| `useLogs` | `useLogs.ts` | `useLogs(params)` log listing (SWR), `useLogStream()` real-time log via WebSocket |
| `useSiteConfigs` | `useSiteConfigs.ts` | `useSiteConfigs()` site list (SWR), `useProbe()` URL probe, `useUpdateSiteConfig()`, `useUpdateFieldMapping()`, `useResetSiteField()`, `useResetAdaptive()` |

---

### API Client (`lib/api.ts`)

Single `apiFetch` base function with automatic 401 redirect and CSRF header injection. All API calls go through named namespaces:

| Namespace | Covers |
|-----------|--------|
| `auth` | login, logout, setup, sessions, profile, avatar, password, check |
| `eh` | search, gallery, images, proxy, favorites, popular, toplists, comments |
| `library` | galleries CRUD, images, tags, progress, artists, image browser (`browseImages`), trash (list/count/restore/permanentDelete/emptyTrash), image favorites, time range/percentiles, checkUpdate |
| `download` | enqueue, jobs, cancel, clear, stats, pause, resume, retry, checkUrl, supportedSites, preview |
| `settings` | credentials, tokens, feature flags, EH site, rate limit, alerts, trash settings |
| `history` | browse history list/record/clear/delete |
| `savedSearches` | saved search CRUD |
| `system` | health, info, cache, storage, reconcile start/status |
| `tags` | list, aliases, implications, autocomplete, translations, blocked, retag, EhTag import, gallery tag update, upsert/batch translation |
| `tokens` | API token CRUD |
| `import_` | browse, start, rescan, libraries, monitor, scan settings, mount points |
| `exportApi` | Kohya export URL builder |
| `plugins` | list plugins |
| `pixiv` | search, searchPublic, illust, user, following, bookmarks, ranking, follow/unfollow |
| `artists` | followed artists |
| `collections` | collection CRUD, add/remove galleries |
| `scheduledTasks` | task listing, enable/disable, manual run |
| `subscriptions` | subscription CRUD, manual check trigger |
| `subscriptionGroups` | subscription group CRUD, run/pause/resume, bulk move |
| `dedup` | dedup stats, review list, keep/whitelist/skip/delete, scan start/stop/progress |
| `users` | User list, create, update, delete |
| `logs` | Log entries list/clear, log level get/set, retention get/set |
| `adminSites` | Site config list/get/update, probe URL, field mapping, reset field, reset adaptive |

#### Image Browser Endpoint

`GET /api/library/images` — cross-gallery image browser with keyset cursor pagination.

| Query Param | Type | Default | Description |
|-------------|------|---------|-------------|
| `tags` | `string[]` | `[]` | Include images matching all listed tags (GIN array contains) |
| `exclude_tags` | `string[]` | `[]` | Exclude images matching any listed tag |
| `cursor` | `string` | — | Opaque HMAC-signed cursor from previous response |
| `limit` | `int` | `40` (max 100) | Page size |
| `sort` | `newest\|oldest` | `newest` | Sort direction on `images.added_at` |
| `gallery_id` | `int` | — | Restrict to a single gallery |

Returns `ImageBrowserResponse`: `{ images: BrowseImage[], next_cursor: string|null, has_next: bool }`.
Blocked tags (per-user) are automatically excluded. Access-controlled via `gallery_access_filter`.

#### Key TypeScript Types (`pwa/src/lib/types.ts`)

| Type | Description |
|------|-------------|
| `BrowseImage` | `{ id, gallery_id, page_num, width, height, thumb_path, file_path, thumbhash, media_type, added_at }` |
| `ImageBrowserResponse` | `{ images: BrowseImage[], next_cursor: string\|null, has_next: boolean, favorited_image_ids: number[] }` |
| `Gallery.display_order` | Optional `'asc' \| 'desc'` — per-source image ordering preference (e.g., Twitter = `desc`) |
| `Gallery.in_reading_list` | `boolean` — per-user reading list membership |
| `ImageTimeRangeResponse` | `{ min_at: string, max_at: string }` — date range for Image Browser scrubber |
| `TimelinePercentilesResponse` | `{ timestamps: string[], total_buckets: number }` — percentile distribution for timeline |
| `WsMessage` | Extended with `event_type`, `resource_type`, `resource_id`, `data` fields for EventBus messages |
| `GallerySearchParams.in_reading_list` | Optional `boolean` — filter by reading list membership |

---

### Lib Utilities (`pwa/src/lib/`)

| File | Description |
|------|-------------|
| `api.ts` | Typed API client — all endpoint namespaces (see above) |
| `types.ts` | TypeScript type definitions |
| `ws.tsx` | WebSocket client — auto-reconnect, message queue, `useWebSocket()` hook |
| `timeUtils.ts` | Date/time formatting helpers |
| `galleryUtils.ts` | Gallery data processing utilities |
| `thumbhash.ts` | Thumbhash encoding/decoding |
| `thumbhash.worker.ts` | Web Worker for thumbhash decoding (offloads main thread) |
| `pageRegistry.ts` | Page configuration registry — route metadata, permissions, nav config |
| `swCacheConfig.ts` | Service Worker cache strategy configuration |

---

### i18n

| Locale | File | Status |
|--------|------|--------|
| `en` | `lib/i18n/en.ts` | Primary (authoritative) |
| `zh-TW` | `lib/i18n/zh-TW.ts` | Traditional Chinese |
| `zh-CN` | `lib/i18n/zh-CN.ts` | Simplified Chinese |
| `ja` | `lib/i18n/ja.ts` | Japanese |
| `ko` | `lib/i18n/ko.ts` | Korean |

- Index: `lib/i18n/index.ts` — exports `t(key, params?)` function
- Missing keys fall back to `en`
- Key convention: `{section}.{description}` (e.g. `browse.failedLoadResults`)
- Parameterised: `t('browse.pageN', { page: '5' })`
- All visible UI text must use `t()` — see CLAUDE.md for exceptions

---

### WebSocket

- URL: `ws[s]://{host}/api/ws` (protocol matches page protocol)
- Connection managed by `useWebSocket()` in `lib/ws.ts`
- Auto-reconnect: 3-second delay after disconnect
- Message type `{ type: 'alert', message: string }` — appended to alerts queue (max 50)
- `dismissAlert(index)` removes an alert from the queue

---

## Infrastructure

### Nginx

Config: `nginx/nginx.conf`

#### Location Blocks

| Location | Rate Limit Zone | Auth | Notes |
|----------|----------------|------|-------|
| `/media/thumbs/` | — | `auth_request /_auth` | Serves `/data/thumbs/`; 7d cache headers |
| `/media/cas/` | — | `auth_request /_auth` | Serves `/data/cas/`; 30d immutable cache |
| `/media/avatars/` | — | `auth_request /_auth` | Serves `/data/avatars/` |
| `/media/libraries/` | — | `auth_request /_auth` | Serves `/mnt/` (external mounts) |
| `/api/auth/login` | `auth_zone` (5r/m) | None | Login rate-limiting |
| `/api/auth/setup` | `auth_zone` (5r/m) | None | Setup rate-limiting |
| `/api/eh/thumb-proxy` | — | None | Nginx proxy cache (7d) for EH CDN thumbnails |
| `/api/eh/image-proxy/` | `eh_proxy` (5r/s) | None | EH image proxy rate-limiting |
| `/api/download/` | `download_zone` (2r/s) | None | Download enqueue rate-limiting |
| `/api/` | `api_zone` (30r/s) | None | General API; WebSocket upgrade enabled |
| `/opds/` | — | None | Passes `Authorization` header; no `auth_request` |
| `/` | — | None | Proxies to `pwa:3000`; WebSocket upgrade enabled |
| `/health` | — | None | Maps to `/api/health` liveness probe |
| `/nginx-health` | — | None | Nginx self-health; no upstream |

#### Caches

| Cache Zone | Storage | TTL | Key |
|------------|---------|-----|-----|
| `thumb_cache` | `/var/cache/nginx/thumb_cache` (512 MB) | 7 days | `$request_uri` |
| `auth_cache` | `/var/cache/nginx/auth_cache` (10 MB) | 5 min (200) / 10s (4xx) | `$http_cookie$http_authorization` |

#### Security Headers

Applied globally: `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy`, `Content-Security-Policy`.

TLS termination is handled by an external reverse proxy (Caddy/Traefik/cloud LB). Nginx listens on HTTP only.

---

### Database

- PostgreSQL 18 (Alpine)
- Schema initialised from `db/init.sql` via `docker-entrypoint-initdb.d`
- Extensions: `pg_trgm` (trigram fuzzy search)
- Migrations: Alembic — `backend/alembic.ini` + `backend/migrations/versions/`
- Connection: asyncpg via SQLAlchemy async engine (`AsyncSessionLocal`)
- Healthcheck: `pg_isready` + `SELECT 1`
- 密碼加密：`password_encryption=scram-sha-256`
- 連線日誌：`log_connections=on`、`log_disconnections=on`

---

### Backup & Recovery

| Script | Description |
|--------|-------------|
| `scripts/backup.sh [backup_dir]` | PostgreSQL `pg_dump` + Redis `BGSAVE`; timestamped output to `./backups/` by default |
| `scripts/restore.sh` | Restore from a backup archive |
| `scripts/backup-cron.sh` | Cron wrapper for scheduled backups |

Credentials are read from `.env` at project root. DB user/name default to `vault`.

---

### Monitoring (Healthchecks)

| Service | Check | Interval |
|---------|-------|----------|
| `nginx` | `wget -q --spider http://127.0.0.1/nginx-health` | 15s |
| `api` | `wget -qO /dev/null http://localhost:8000/api/health` | 15s |
| `worker` | Redis `PING` + `pgrep arq worker.WorkerSettings` | 15s |
| `pwa` | `wget -q --spider http://127.0.0.1:3000` | 15s |
| `postgres` | `pg_isready` + `SELECT 1` | 5s |
| `redis` | `redis-cli ping` | 5s |

---

## Key Redis Keys

| Key Pattern | TTL | Description |
|-------------|-----|-------------|
| `session:{user_id}:{token}` | 30 days | Active user session |
| `eh:gallery:{gid}` | 1h | EH gallery metadata cache |
| `eh:imagelist:{gid}` | 1h | EH image token list cache |
| `thumb:proxied:{gid}:{page}` | 24h | EH proxied image cache |
| `download:sem:ehentai` | — | EH download semaphore counter |
| `download:sem:pixiv` | — | Pixiv download semaphore counter |
| `download:sem:other` | — | Other source semaphore counter |
| `setting:{feature}` | — | Runtime feature flag override |
| `watcher:enabled` | — | Library watcher enabled flag |
| `watcher:status` | — | Watcher running status + paths (JSON) |
| `rescan:progress` | — | Rescan job progress |
| `rescan:cancel` | — | Rescan cancellation flag |
| `system:alerts` | — | System alert messages |
| `dedup:progress:status` | — | Dedup scan status (`idle`/`running`/`done`/`error`) |
| `dedup:progress:signal` | — | Scan control signal (`stop`) |
| `dedup:progress:current` | — | Processed pairs count |
| `dedup:progress:total` | — | Total pairs to process |
| `dedup:progress:tier` | — | Currently active tier |
| `dedup:progress:mode` | — | Scan mode |
| `download:pid:{job_id}` | — | gallery-dl subprocess PID（cancel 用，best-effort SIGTERM） |
| `download:pause:{job_id}` | 24h | 統一 soft-pause flag，所有下載引擎共用（key 存在即暫停） |
| `download:cancel:{job_id}` | 1h | Cancel flag for native downloads |
| `setting:retry_enabled` | — | Auto-retry feature toggle |
| `setting:retry_max_retries` | — | Max retry attempts setting |
| `setting:retry_base_delay_minutes` | — | Retry backoff base delay setting |
| `cron:retry_downloads:*` | — | Retry cron job state (last_run, last_status, enabled, cron_expr) |
| `pixiv:access_token` | — | Pixiv OAuth access token cache |
| `pixiv:token_lock` | — | Pixiv token refresh lock |
| `rate_limit:override:unlocked` | — | Manual full-speed unlock flag |
| `rate_limit:schedule:enabled` | — | Scheduled rate limiting enabled flag |
| `rate_limit:schedule:start_hour` | — | Rate limit schedule start hour |
| `rate_limit:schedule:end_hour` | — | Rate limit schedule end hour |
| `rate_limit:schedule:active` | — | Currently active rate limit flag (set by `rate_limit_schedule_job`) |
| `rate_limit:schedule:mode` | — | Rate limit schedule mode |
| `rate_limit:config:{source}:delay_ms` | — | Per-source rate limit delay (ms) |
| `scan:schedule:enabled` | — | Scheduled library scan enabled flag |
| `scan:schedule:interval_hours` | — | Scheduled scan interval (hours) |
| `scan:schedule:last_run` | — | Last scheduled scan timestamp |
| `import:batch:{batch_id}` | — | Batch import tracking (progress JSON) |
| `import:progress:{gallery_id}` | — | Single gallery import progress |
| `reconcile:last_result` | 30 days | Last reconciliation result (JSON) |
| `setting:trash_enabled` | — | Trash (soft-delete) feature toggle |
| `setting:trash_retention_days` | — | Days to keep soft-deleted galleries before permanent deletion |
| `cron:trash_gc:*` | — | Trash GC cron job state |
| `cron:ehtag_sync:*` | — | EhTag sync cron job state |
| `events:recent` | — | EventBus recent event list (max 200, JSON) |
| `events:{event_type}` | Pub/Sub | Per-type event channel (e.g., `events:gallery.updated`) |
| `events:all` | Pub/Sub | All-event broadcast channel |
| `setting:tag_translation_enabled` | — | Tag translation feature toggle |
| `system:disk_low` | 600s | Disk space low flag — value is free GB as string; set by `disk_monitor_job` cron, read by `download_job` pre-flight + `retry_failed_downloads_job` gate |
| `adaptive:{source_id}` | 24h | Adaptive rate limiting state (JSON: sleep_multiplier, http_timeout_add, credential_warning, consecutive_success, last_signal, last_signal_at). Hot path via Lua script |
| `adaptive:dirty` | — | Set of source_ids with adaptive state changes pending DB persistence. SPOP'd by `adaptive_persist_job` cron every 5 min |
| `site_config:invalidate` | Pub/Sub | SiteConfigService cache invalidation (payload = source_id) |

---

## Tag System

Tag format: `{namespace}:{name}`

Standard namespaces: `artist`, `character`, `copyright`, `general`, `meta`, `language`

### Tag Translations

- Translations stored in `tag_translations` table (keyed by `namespace + name + language`)
- EhTag translations synced via `ehtag_sync_job` (CDN JSON → bulk upsert)
- DB stores translations in `zh` (Simplified Chinese); `zh-TW` is derived at query time via **OpenCC** (`opencc-python-reimplemented`, `s2twp` converter)
- Translation endpoint: `GET /api/tags/translations?language={lang}&tags=...`
- Feature toggle: `setting:tag_translation_enabled` (Redis, default `true`)

### Sync Flow

```
parse metadata.json / tags.txt
  → resolve aliases → canonical tag
  → expand implications (recursive)
  → deduplicate
  → write gallery_tags + update tags_array
  → update tags.count
```

### Search Syntax

| Syntax | Description |
|--------|-------------|
| `character:rem` | Exact tag match (GIN array index) |
| `-general:sketch` | Exclude tag |
| `title:"re zero"` | Fuzzy title search (pg_trgm) |
| `source:ehentai` | Source filter |
| `rating:>=4` | Rating filter |
| `pages:>=20` | Page count filter |
| `favorited:true` | Favorites only |
| `language:japanese` | Language filter |

Sort options: `added_at` (default), `rating`, `posted_at`, `pages`, `title`

---

## Upgrade Compatibility Notes

| 項目 | 限制 | 原因 |
|------|------|------|
| Python ≤ 3.13 | arq 0.27 不支援 3.14+ | `asyncio.get_event_loop()` 在 3.14 已移除 |
| numpy ≥ 2.4 | slim 映像無 gcc | 2.3.x 無 cp314 wheel，需 source build |
| opencc-python-reimplemented | 0.1.7 | 繁中轉換（`s2twp`），`routers/tag.py` 用 |
| Tailwind 4 | CSS-first，無 JS config | `@theme inline` + `@custom-variant dark` |
| React 19 | `useRef()` 須傳初始值 | 不再自動推斷 `undefined` |
| Next.js 16 | 測試須 mock `next/navigation` | App Router context 更嚴格 |
