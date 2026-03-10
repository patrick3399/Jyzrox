# Jyzrox Architecture (v0.1)

> Codebase audit, 2026-03-10. Read from source files — do not update manually; regenerate from source.

---

## Service Topology

### Docker Compose Services

| Service | Image / Build | Port | Networks | Resource Limits |
|---------|--------------|------|----------|-----------------|
| `nginx` | `./nginx` | `${HTTP_PORT:-35689}:80` | frontend | 1 CPU / 256 MB |
| `api` | `./backend` (uvicorn, port 8000) | internal | frontend + backend | 2 CPU / 2 GB |
| `worker` | `./backend` (arq worker.WorkerSettings) | — | frontend + backend | 2 CPU / 2 GB |
| `pwa` | `./pwa` (Next.js, port 3000) | internal | frontend | 1 CPU / 512 MB |
| `postgres` | `postgres:15-alpine` | internal | backend | 2 CPU / 2 GB |
| `redis` | `redis:7-alpine` | internal | backend | 1 CPU / 1 GB |

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
└── training/                 # Kohya export datasets
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
| `/api/eh` | `routers/eh.py` | Session | EH search, gallery, images, proxy, favorites, popular, toplists |
| `/api/pixiv` | `routers/pixiv.py` | Session | Pixiv search, illust, user, following |
| `/api/library` | `routers/library.py` | Session | Gallery CRUD, images, tags, progress, artists |
| `/api/download` | `routers/download.py` | Session | Enqueue, list/cancel jobs, stats |
| `/api/settings` | `routers/settings.py` | Session | Credentials, API tokens, feature flags, EH site toggle, rate limit |
| `/api/ws` | `routers/ws.py` | Session | WebSocket at `/api/ws/ws` |
| `/api/search` | `routers/search.py` | Session | Full-text gallery search, saved searches |
| `/api/tags` | `routers/tag.py` | Session | Tag listing, aliases, implications, autocomplete, translations, blocked, retag |
| `/api/import` | `routers/import_router.py` | Session | Local import, library paths, rescan, file browser, monitor, scheduled scan |
| `/api/export` | `routers/export.py` | Session | Kohya zip export |
| `/api/external/v1` | `routers/external.py` | `X-API-Token` header | External API for third-party integrations |
| `/api/history` | `routers/history.py` | Session | Browse history CRUD |
| `/api/plugins` | `routers/plugins.py` | Session | List registered plugins |
| `/api/artists` | `routers/artists.py` | Session | Followed artists (Pixiv/EH) |
| `/opds` | `routers/opds.py` | HTTP Basic Auth | OPDS catalog for e-readers |
| `/api/health` | `main.py` inline | Public | Liveness probe |

---

### Database Schema

#### Tables

| Table | Description | Key Columns |
|-------|-------------|-------------|
| `users` | User accounts | `id`, `username` UNIQUE, `password_hash`, `role`, `locale`, `avatar_style` |
| `galleries` | Gallery records | `id`, `(source, source_id)` UNIQUE, `title`, `tags_array TEXT[]`, `download_status`, `artist_id`, `library_path` |
| `blobs` | CAS file store | `sha256` PK, `file_size`, `media_type`, `width`, `height`, `duration`, `phash*`, `extension`, `storage`, `ref_count` |
| `images` | Gallery pages | `id`, `gallery_id` FK, `page_num`, `blob_sha256` FK, `tags_array TEXT[]` |
| `tags` | Tag registry | `id`, `(namespace, name)` UNIQUE, `count` |
| `tag_aliases` | Tag alias map | `(alias_namespace, alias_name)` PK → `canonical_id` FK |
| `tag_implications` | Tag inference rules | `(antecedent_id, consequent_id)` PK |
| `gallery_tags` | Gallery↔Tag join | `(gallery_id, tag_id)` PK, `confidence`, `source` |
| `image_tags` | Image↔Tag join | `(image_id, tag_id)` PK, `confidence` |
| `download_jobs` | ARQ job tracking | `id` UUID PK, `url`, `source`, `status`, `progress` JSONB, `error` |
| `read_progress` | Per-gallery read cursor | `gallery_id` PK, `last_page`, `last_read_at` |
| `credentials` | Source credentials (encrypted) | `source` PK, `credential_type`, `value_encrypted` BYTEA |
| `api_tokens` | External API tokens | `id` UUID PK, `user_id` FK, `token_hash` UNIQUE, `token_plain`, `expires_at` |
| `browse_history` | EH browse history | `id`, `(user_id, source, source_id)` UNIQUE, `gid`, `token`, `viewed_at` |
| `saved_searches` | Persisted search queries | `id`, `user_id` FK, `name`, `query`, `params` JSONB |
| `tag_translations` | Tag i18n (zh default) | `(namespace, name, language)` PK, `translation` |
| `blocked_tags` | Per-user tag blocklist | `id`, `(user_id, namespace, name)` UNIQUE |
| `library_paths` | User-configured scan paths | `id`, `path` UNIQUE, `label`, `enabled`, `monitor` |
| `plugin_config` | Plugin enable/config | `source_id` PK, `enabled`, `config_json` JSONB |
| `followed_artists` | Followed artist records | `id`, `(user_id, source, artist_id)` UNIQUE, `auto_download`, `last_illust_id` |
| `audit_logs` | Security audit trail | `id`, `user_id` FK, `action`, `resource_type`, `ip_address`, `created_at` |

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
| `FollowedArtist` | `followed_artists` |

---

### Worker Pipeline (ARQ)

Entry: `arq worker.WorkerSettings`

#### Job Functions

| Function | Trigger | Description |
|----------|---------|-------------|
| `download_job` | API enqueue | Download gallery via plugin registry; falls back to gallery-dl subprocess |
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

#### Standard Pipeline

```
download_job → import_job → thumbnail_job
                          └→ tag_job (if enabled)
```

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

#### Registry (`plugins/registry.py`)

Singleton `plugin_registry` (`PluginRegistry`). Routes URLs to the first matching `SourcePlugin`; `gallery_dl` is the registered fallback. Browsers and taggers are keyed by `source_id`.

#### Built-in Plugins

| Plugin | source_id | ABCs | Description |
|--------|-----------|------|-------------|
| `ehentai/source.py` | `ehentai` | SourcePlugin | Native EH download via `EhClient` |
| `ehentai/browse.py` | `ehentai` | BrowsePlugin | EH search/favorites/popular/toplists |
| `pixiv/source.py` | `pixiv` | SourcePlugin | Pixiv artwork download via OAuth API |
| `gallery_dl/source.py` | `gallery_dl` | SourcePlugin | gallery-dl subprocess fallback (any URL) |

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

#### Storage Paths

| Field | Default | Description |
|-------|---------|-------------|
| `data_gallery_path` | `/data/gallery` | Gallery download root |
| `data_thumbs_path` | `/data/thumbs` | WebP thumbnail root |
| `data_training_path` | `/data/training` | Kohya export root |
| `data_avatars_path` | `/data/avatars` | User avatar upload root |
| `data_cas_path` | `/data/cas` | Content-Addressable Storage root |
| `data_library_path` | `/data/library` | Library symlink root |
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

## Frontend (Next.js 15 PWA)

Source root: `pwa/src/`

### Page Routes

| Route | File | Description |
|-------|------|-------------|
| `/` | `app/page.tsx` | Dashboard — recent galleries + active downloads |
| `/login` | `app/login/page.tsx` | Username + password login form |
| `/setup` | `app/setup/page.tsx` | First-run admin account creation |
| `/browse` | `app/browse/page.tsx` | E-Hentai search + quick download |
| `/browse/[gid]/[token]` | `app/browse/[gid]/[token]/page.tsx` | EH gallery detail page |
| `/browse/read/[gid]/[token]` | `app/browse/read/[gid]/[token]/page.tsx` | EH online reader (proxy mode) |
| `/library` | `app/library/page.tsx` | Local gallery grid with tag/rating/source filters |
| `/library/[id]` | `app/library/[id]/page.tsx` | Gallery detail — tags, thumbnails, read/favorite |
| `/reader/[galleryId]` | `app/reader/[galleryId]/page.tsx` | Full local reader (single/webtoon/double-page) |
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
| `/share-target` | `app/share-target/page.tsx` | PWA Web Share Target handler |

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

---

### Hooks

All hooks in `pwa/src/hooks/`.

| Hook | File | Description |
|------|------|-------------|
| `useAuth` | `useAuth.ts` | `login(username, password)`, `logout()`, session state |
| `useProfile` | `useProfile.ts` | User profile data (SWR) |
| `useGalleries` | `useGalleries.ts` | `useLibraryGalleries`, `useLibraryGallery`, `useGalleryImages` (SWR) |
| `useDownloadQueue` | `useDownloadQueue.ts` | `useDownloadJobs` (3s refresh), `useEnqueueDownload`, `useCancelJob` |
| `useImport` | `useImport.ts` | Import flow state and progress |
| `useArtists` | `useArtists.ts` | Followed artists listing and actions |
| `useTagTranslations` | `useTagTranslations.ts` | Tag translation lookup (SWR) |

---

### API Client (`lib/api.ts`)

Single `apiFetch` base function with automatic 401 redirect and CSRF header injection. All API calls go through named namespaces:

| Namespace | Covers |
|-----------|--------|
| `auth` | login, logout, setup, sessions, profile, avatar, password, check |
| `eh` | search, gallery, images, proxy, favorites, popular, toplists, comments |
| `library` | galleries CRUD, images, tags, progress, artists |
| `download` | enqueue, jobs, cancel, clear, stats, pause, resume |
| `settings` | credentials, tokens, feature flags, EH site, rate limit, alerts |
| `history` | browse history list/record/clear/delete |
| `savedSearches` | saved search CRUD |
| `system` | health, info, cache |
| `tags` | list, aliases, implications, autocomplete, translations, blocked, retag |
| `tokens` | API token CRUD |
| `import_` | browse, start, rescan, libraries, monitor, scan settings, mount points |
| `exportApi` | Kohya export URL builder |
| `plugins` | list plugins |
| `pixiv` | search, illust, user, following |
| `artists` | followed artists |

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

- PostgreSQL 15 (Alpine)
- Schema initialised from `db/init.sql` via `docker-entrypoint-initdb.d`
- Extensions: `pg_trgm` (trigram fuzzy search)
- Migrations: Alembic — `backend/alembic.ini` + `backend/migrations/versions/`
- Connection: asyncpg via SQLAlchemy async engine (`AsyncSessionLocal`)
- Healthcheck: `pg_isready` + `SELECT 1`

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

---

## Tag System

Tag format: `{namespace}:{name}`

Standard namespaces: `artist`, `character`, `copyright`, `general`, `meta`, `language`

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
