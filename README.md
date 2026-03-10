# Jyzrox

> **Work in Progress** — This project is under active development. Features may be incomplete or change without notice.
>
> **WARNING** — This project is created via Vibe Coding and may contain unknown security risks. Using this program may result in your account being banned on external websites.

A self-hosted gallery management platform built with Docker Compose. Browse, download, organize, and read galleries from various sources with a modern PWA interface.

## Features

- **Gallery Browser** — Search and browse E-Hentai / Pixiv with favorites sync
- **Download Engine** — Plugin-based downloads (native E-Hentai & Pixiv, gallery-dl fallback for 25+ sites) with progress tracking
- **Reader** — Single page, double page, and webtoon (scroll) modes with touch/keyboard navigation
- **Library** — Local gallery management with tag filtering, rating, and read progress
- **Tag System** — Namespace-based tags with alias, implication, and blocked tag support
- **Subscriptions** — Follow artists with automatic new-work checking
- **Collections** — Organize galleries into custom collections
- **PWA** — Installable, mobile-friendly, works offline for local content

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI + SQLAlchemy (asyncpg) + ARQ |
| Frontend | Next.js 16 App Router (PWA) |
| Database | PostgreSQL 18 + Redis 8 |
| Proxy | Nginx |
| Downloads | Plugin system + gallery-dl fallback |

API documentation is auto-generated from code and always up-to-date: Swagger UI at `/api/docs`, ReDoc at `/api/redoc`.

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

- [x] Pixiv source integration
- [x] Subscription system (artist following)
- [x] Plugin-driven credential management
- [x] AI-based auto-tagging (WD14)
- [ ] Duplicate detection and management
- [ ] Multi-user support

## License

[MIT + Commons Clause](LICENSE) — Free to use, modify, and distribute. Commercial sale is not permitted.
