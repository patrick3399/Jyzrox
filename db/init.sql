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

CREATE TABLE IF NOT EXISTS blobs (
    sha256        TEXT PRIMARY KEY,
    file_size     BIGINT NOT NULL,
    media_type    TEXT NOT NULL DEFAULT 'image',
    width         INT,
    height        INT,
    phash         TEXT,
    phash_int     BIGINT,
    phash_q0      SMALLINT,
    phash_q1      SMALLINT,
    phash_q2      SMALLINT,
    phash_q3      SMALLINT,
    extension     TEXT NOT NULL,
    storage       TEXT NOT NULL DEFAULT 'cas',
    external_path TEXT,
    ref_count     INT NOT NULL DEFAULT 0,
    created_at    TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_blobs_phash ON blobs (phash) WHERE phash IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_blobs_phash_q0 ON blobs(phash_q0) WHERE phash_q0 IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_blobs_phash_q1 ON blobs(phash_q1) WHERE phash_q1 IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_blobs_phash_q2 ON blobs(phash_q2) WHERE phash_q2 IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_blobs_phash_q3 ON blobs(phash_q3) WHERE phash_q3 IS NOT NULL;

CREATE TABLE IF NOT EXISTS images (
    id              BIGSERIAL PRIMARY KEY,
    gallery_id      BIGINT NOT NULL REFERENCES galleries(id) ON DELETE CASCADE,
    page_num        INT NOT NULL,
    filename        TEXT,
    blob_sha256     TEXT NOT NULL REFERENCES blobs(sha256),
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
CREATE INDEX IF NOT EXISTS idx_images_blob         ON images (blob_sha256);

-- #4: galleries.source (single-column) — used in WHERE source = 'pixiv' filters
-- Note: idx_galleries_source above covers (source, source_id); this covers source-only lookups.
CREATE INDEX IF NOT EXISTS idx_galleries_source_only ON galleries (source);

-- #5: tags.count DESC — used in ORDER BY count DESC for tag listing
CREATE INDEX IF NOT EXISTS idx_tags_count ON tags (count DESC);

CREATE INDEX IF NOT EXISTS idx_gallery_tags_tag ON gallery_tags (tag_id);
CREATE INDEX IF NOT EXISTS idx_image_tags_tag ON image_tags (tag_id);
CREATE INDEX IF NOT EXISTS idx_download_jobs_status ON download_jobs (status);

-- Composite indexes for keyset pagination (sort_col DESC, id DESC)
CREATE INDEX IF NOT EXISTS idx_galleries_added_at_id ON galleries (added_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_galleries_rating_id   ON galleries (rating DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_galleries_pages_id    ON galleries (pages DESC NULLS LAST, id DESC);

-- ── Browse History ────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS browse_history (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source      TEXT NOT NULL,
    source_id   TEXT NOT NULL,
    title       TEXT,
    thumb       TEXT,
    gid         BIGINT,
    token       TEXT,
    viewed_at   TIMESTAMPTZ DEFAULT now(),
    UNIQUE (user_id, source, source_id)
);
CREATE INDEX IF NOT EXISTS idx_browse_history_user ON browse_history (user_id, viewed_at DESC);

-- ── Saved Searches ────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS saved_searches (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    query       TEXT DEFAULT '',
    params      JSONB DEFAULT '{}',
    created_at  TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_saved_searches_user ON saved_searches (user_id, created_at DESC);

-- ── Tag Translations ──────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS tag_translations (
    namespace   TEXT NOT NULL,
    name        TEXT NOT NULL,
    language    TEXT NOT NULL DEFAULT 'zh',
    translation TEXT NOT NULL,
    PRIMARY KEY (namespace, name, language)
);

-- ── Blocked Tags ──────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS blocked_tags (
    id          BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    namespace   TEXT NOT NULL,
    name        TEXT NOT NULL,
    UNIQUE (user_id, namespace, name)
);
CREATE INDEX IF NOT EXISTS idx_blocked_tags_user ON blocked_tags (user_id);

-- ── Library Paths ──────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS library_paths (
    id          SERIAL PRIMARY KEY,
    path        TEXT NOT NULL UNIQUE,
    label       TEXT,
    enabled     BOOLEAN NOT NULL DEFAULT TRUE,
    monitor     BOOLEAN NOT NULL DEFAULT TRUE,
    added_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Gallery extensions for library management
ALTER TABLE galleries ADD COLUMN IF NOT EXISTS last_scanned_at TIMESTAMPTZ;
ALTER TABLE galleries ADD COLUMN IF NOT EXISTS library_path TEXT;

-- pHash quarter columns for pigeonhole pre-filter (scalability)
ALTER TABLE blobs ADD COLUMN IF NOT EXISTS phash_int BIGINT;
ALTER TABLE blobs ADD COLUMN IF NOT EXISTS phash_q0 SMALLINT;
ALTER TABLE blobs ADD COLUMN IF NOT EXISTS phash_q1 SMALLINT;
ALTER TABLE blobs ADD COLUMN IF NOT EXISTS phash_q2 SMALLINT;
ALTER TABLE blobs ADD COLUMN IF NOT EXISTS phash_q3 SMALLINT;
CREATE INDEX IF NOT EXISTS idx_blobs_phash_q0 ON blobs(phash_q0) WHERE phash_q0 IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_blobs_phash_q1 ON blobs(phash_q1) WHERE phash_q1 IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_blobs_phash_q2 ON blobs(phash_q2) WHERE phash_q2 IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_blobs_phash_q3 ON blobs(phash_q3) WHERE phash_q3 IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_galleries_library_path ON galleries (library_path);
CREATE INDEX IF NOT EXISTS idx_galleries_last_scanned ON galleries (last_scanned_at NULLS FIRST);

-- ── Plugin Config ────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS plugin_config (
    source_id   TEXT PRIMARY KEY,
    enabled     BOOLEAN DEFAULT TRUE,
    config_json JSONB DEFAULT '{}',
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);
