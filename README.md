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
  gallery-dl runtime, external API tokens, and optional AI tagging; use scripts
  for backup and restore.

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

## License

[MIT + Commons Clause](LICENSE). Commercial sale is not permitted.
