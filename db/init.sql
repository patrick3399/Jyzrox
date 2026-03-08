-- Jyzrox — PostgreSQL Schema
-- rev 1.1 / 2026-03

-- ── Tables ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS users (
    id              BIGSERIAL PRIMARY KEY,
    username        TEXT UNIQUE NOT NULL,
    email           TEXT UNIQUE,
    password_hash   TEXT NOT NULL,
    role            TEXT DEFAULT 'admin',
    created_at      TIMESTAMPTZ DEFAULT now(),
    last_login_at   TIMESTAMPTZ,
    avatar_style    TEXT DEFAULT 'gravatar'
);

-- No default user: first-run setup is done via POST /api/auth/setup

CREATE TABLE IF NOT EXISTS galleries (
    id              BIGSERIAL PRIMARY KEY,
    source          TEXT NOT NULL,
    source_id       TEXT NOT NULL,
    title           TEXT,
    title_jpn       TEXT,
    category        TEXT,
    language        TEXT,
    pages           INT,
    posted_at       TIMESTAMPTZ,
    added_at        TIMESTAMPTZ DEFAULT now(),
    rating          SMALLINT DEFAULT 0,
    favorited       BOOLEAN DEFAULT false,
    uploader        TEXT,
    parent_id       BIGINT REFERENCES galleries(id),
    download_status TEXT DEFAULT 'proxy_only',
    import_mode     TEXT,
    tags_array      TEXT[] DEFAULT '{}',
    UNIQUE (source, source_id)
);

CREATE TABLE IF NOT EXISTS images (
    id              BIGSERIAL PRIMARY KEY,
    gallery_id      BIGINT NOT NULL REFERENCES galleries(id) ON DELETE CASCADE,
    page_num        INT NOT NULL,
    filename        TEXT,
    width           INT,
    height          INT,
    file_path       TEXT,
    thumb_path      TEXT,
    file_size       BIGINT,
    file_hash       TEXT,
    media_type      TEXT DEFAULT 'image',
    duration        REAL,
    duplicate_of    BIGINT REFERENCES images(id),
    tags_array      TEXT[] DEFAULT '{}',
    UNIQUE (gallery_id, page_num)
);

CREATE TABLE IF NOT EXISTS tags (
    id              BIGSERIAL PRIMARY KEY,
    namespace       TEXT NOT NULL,
    name            TEXT NOT NULL,
    count           INT DEFAULT 0,
    UNIQUE (namespace, name)
);

CREATE TABLE IF NOT EXISTS tag_aliases (
    alias_namespace TEXT NOT NULL,
    alias_name      TEXT NOT NULL,
    canonical_id    BIGINT NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (alias_namespace, alias_name)
);

CREATE TABLE IF NOT EXISTS tag_implications (
    antecedent_id   BIGINT NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    consequent_id   BIGINT NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (antecedent_id, consequent_id)
);

CREATE TABLE IF NOT EXISTS gallery_tags (
    gallery_id      BIGINT NOT NULL REFERENCES galleries(id) ON DELETE CASCADE,
    tag_id          BIGINT NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    confidence      REAL DEFAULT 1.0,
    source          TEXT DEFAULT 'metadata',
    PRIMARY KEY (gallery_id, tag_id)
);

CREATE TABLE IF NOT EXISTS image_tags (
    image_id        BIGINT NOT NULL REFERENCES images(id) ON DELETE CASCADE,
    tag_id          BIGINT NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    confidence      REAL,
    PRIMARY KEY (image_id, tag_id)
);

CREATE TABLE IF NOT EXISTS download_jobs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    url             TEXT NOT NULL,
    source          TEXT,
    status          TEXT DEFAULT 'queued',
    progress        JSONB DEFAULT '{}',
    error           TEXT,
    created_at      TIMESTAMPTZ DEFAULT now(),
    finished_at     TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS read_progress (
    gallery_id      BIGINT PRIMARY KEY REFERENCES galleries(id) ON DELETE CASCADE,
    last_page       INT DEFAULT 0,
    last_read_at    TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS credentials (
    source          TEXT PRIMARY KEY,
    credential_type TEXT NOT NULL,
    value_encrypted BYTEA,
    expires_at      TIMESTAMPTZ,
    last_verified   TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS api_tokens (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name            TEXT,
    token_hash      TEXT UNIQUE NOT NULL,
    token_plain     TEXT,            -- raw token value for display
    created_at      TIMESTAMPTZ DEFAULT now(),
    last_used_at    TIMESTAMPTZ,
    expires_at      TIMESTAMPTZ
);

-- ── pg_trgm and GIN Indexes (tag search performance) ────────────────────────────

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX IF NOT EXISTS idx_galleries_tags_gin ON galleries USING GIN (tags_array);
CREATE INDEX IF NOT EXISTS idx_images_tags_gin    ON images    USING GIN (tags_array);
CREATE INDEX IF NOT EXISTS idx_galleries_title_trgm ON galleries USING GIN (title gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_galleries_title_jpn_trgm ON galleries USING GIN (title_jpn gin_trgm_ops);

-- ── Regular Indexes ──────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_galleries_source    ON galleries (source, source_id);
CREATE INDEX IF NOT EXISTS idx_galleries_added_at  ON galleries (added_at DESC);
CREATE INDEX IF NOT EXISTS idx_galleries_rating    ON galleries (rating);
CREATE INDEX IF NOT EXISTS idx_galleries_favorited ON galleries (favorited) WHERE favorited = true;
CREATE INDEX IF NOT EXISTS idx_images_gallery      ON images (gallery_id, page_num);
CREATE INDEX IF NOT EXISTS idx_images_hash         ON images (file_hash);
CREATE INDEX IF NOT EXISTS idx_images_duplicate    ON images (duplicate_of) WHERE duplicate_of IS NOT NULL;

-- #4: galleries.source (single-column) — used in WHERE source = 'pixiv' filters
-- Note: idx_galleries_source above covers (source, source_id); this covers source-only lookups.
CREATE INDEX IF NOT EXISTS idx_galleries_source_only ON galleries (source);

-- #5: tags.count DESC — used in ORDER BY count DESC for tag listing
CREATE INDEX IF NOT EXISTS idx_tags_count ON tags (count DESC);

CREATE INDEX IF NOT EXISTS idx_gallery_tags_tag ON gallery_tags (tag_id);
CREATE INDEX IF NOT EXISTS idx_image_tags_tag ON image_tags (tag_id);
CREATE INDEX IF NOT EXISTS idx_download_jobs_status ON download_jobs (status);
