# Jyzrox

Self-hosted gallery management platform for browsing, downloading, organizing,
and reading galleries from E-Hentai, Pixiv, and gallery-dl sources.

> Work in progress. Self-host for personal use only.
> External site integrations may violate provider terms or risk account restrictions.

## Pipeline

Jyzrox is built around a server-side acquisition pipeline rather than a
file-only comic library. Remote sources, gallery-dl URLs, and local folders are
normalized into the same local library model:

```text
source browsing or local import
→ credential-aware download queue
→ CAS-backed gallery/image ingest
→ thumbnails, thumbhash, pHash, optional AI tags
→ dedup review, search, reader, OPDS/RSS/API access
```

The main workflow is turning remote and local gallery sources into a searchable,
readable, self-hosted library.

## Features

- Browse E-Hentai and Pixiv with source detail pages, image proxying, and
  online reader flows.
- Acquire galleries through native E-Hentai/Pixiv downloads, gallery-dl
  fallback, local folder import, subscriptions, and PWA share targets.
- Run credential-aware queues with progress tracking, retry, pause/resume,
  crash recovery, and per-site tuning.
- Normalize media into a content-addressed library with gallery/image records,
  thumbnails, thumbhash placeholders, filesystem watches, scheduled scans, and
  reconciliation.
- Manage galleries with tags, aliases, implications, translations, ratings,
  collections, reading lists, history, saved searches, and read progress.
- Read through an installable PWA with single-page, spread, and webtoon modes,
  plus touch, keyboard, zoom, image actions, and similar-image lookup.
- Track artists and subscriptions with grouped scheduling, automatic download,
  and manual checks.
- Integrate with external readers and tools through authenticated OPDS,
  RSS/Atom feeds, and API tokens.
- Review duplicates with SHA-256 exact matching, pHash scanning, heuristic
  classification, optional OpenCV verification, and a review queue.
- Administer users, credentials, logs, scheduled tasks, site settings,
  gallery-dl runtime, database backups, external API tokens, and optional AI
  tagging.

## Tech Stack

| Layer | Stack |
| --- | --- |
| Backend | FastAPI + SQLAlchemy (asyncpg) + SAQ |
| Frontend | Next.js 16 App Router (PWA) |
| Database | PostgreSQL 18 + Redis 8 |
| Proxy | Nginx |
| Downloads | Plugin system + gallery-dl fallback |

## Quick Start

```bash
cp .env.example .env
docker compose up -d
```

Open `http://localhost:35689`. The first visit starts the setup flow.

API documentation is available after login at `/api/docs` and
`/api/openapi.json`.

## Operations

### Database backups

Jyzrox includes an admin database backup task. The worker runs
`database_backup_job` daily at `02:00` by default, and admins can trigger it
manually from Scheduled Tasks or `POST /api/admin/backups/run`.

Backups are compressed PostgreSQL dumps stored under `/data/backups` inside the
container, which maps to `${JYZROX_DATA_ROOT}/data/backups` in Docker Compose.
Each dump has a JSON manifest, and the built-in retention keeps the latest 14
successful backups by default. The admin API can list and delete backup files;
restore remains an operator action using `scripts/restore.sh`.

The legacy `scripts/backup.sh` script is still available for manual operator
backups that also copy Redis RDB files and optionally encrypt the output.

### gallery-dl runtime

The Docker image ships a `gallery-dl` bootstrap/fallback copy, but normal
`docker compose build` is not the intended update path for the download engine.
Runtime `gallery-dl` lives in the isolated `/opt/gallery-dl` volume, mounted
from `${JYZROX_DATA_ROOT}/venv`, and is managed by the admin gallery-dl upgrade
and rollback actions.

The worker creates or repairs the isolated venv on startup. The active venv must
own its own `bin/gallery-dl`; if that entry point is missing, the worker rebuilds
the venv instead of silently falling back to system packages.

**Upgrading from an earlier release:** the host path changed from
`${JYZROX_DATA_ROOT}/gallery-dl-venv` to `${JYZROX_DATA_ROOT}/venv`. Rename the
directory before restarting containers:

```bash
mv "${JYZROX_DATA_ROOT}/gallery-dl-venv" "${JYZROX_DATA_ROOT}/venv"
```

## License

[MIT + Commons Clause](LICENSE). Commercial sale is not permitted.
