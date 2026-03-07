# Jyzrox

> **Work in Progress** — This project is under active development. Features may be incomplete or change without notice.

A self-hosted gallery management platform built with Docker Compose. Browse, download, organize, and read galleries from various sources with a modern PWA interface.

## Features

- **Gallery Browser** — Search and browse E-Hentai with favorites sync
- **Download Engine** — Queue-based downloads via gallery-dl with progress tracking
- **Reader** — Single page, double page, and webtoon (scroll) modes with touch/keyboard navigation
- **Library** — Local gallery management with tag filtering, rating, and read progress
- **Tag System** — Namespace-based tags with alias and implication support
- **PWA** — Installable, mobile-friendly, works offline for local content

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI + SQLAlchemy (asyncpg) + ARQ |
| Frontend | Next.js 15 App Router (PWA) |
| Database | PostgreSQL 15 + Redis 7 |
| Proxy | Nginx |
| Downloads | gallery-dl |

## Quick Start

```bash
# Clone and configure
git clone https://github.com/patrick3399/Jyzrox.git
cd Jyzrox
cp .env.example .env  # Edit with your settings

# Launch
docker compose up -d

# Access at http://localhost (first visit → setup page)
```

## Roadmap

- [ ] Pixiv source integration
- [ ] AI-based auto-tagging (WD14)
- [ ] Duplicate detection and management
- [ ] Batch operations (tag editing, export)
- [ ] Multi-user support
- [ ] Mobile gesture improvements

## License

[MIT + Commons Clause](LICENSE) — Free to use, modify, and distribute. Commercial sale is not permitted.
