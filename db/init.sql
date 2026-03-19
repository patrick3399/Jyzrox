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
    avatar_style    TEXT DEFAULT 'gravatar',
    locale          TEXT DEFAULT 'en'
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
    download_status TEXT DEFAULT 'proxy_only',
    import_mode     TEXT,
    tags_array      TEXT[] DEFAULT '{}',
    source_url      TEXT,
    metadata_updated_at TIMESTAMPTZ,
    UNIQUE (source, source_id)
);

CREATE TABLE IF NOT EXISTS blobs (
    sha256        TEXT PRIMARY KEY,
    file_size     BIGINT NOT NULL,
    media_type    TEXT NOT NULL DEFAULT 'image',
    width         INT,
    height        INT,
    duration      FLOAT,
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
    finished_at     TIMESTAMPTZ,
    user_id         BIGINT REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS read_progress (
    user_id         BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    gallery_id      BIGINT NOT NULL REFERENCES galleries(id) ON DELETE CASCADE,
    last_page       INT DEFAULT 0,
    last_read_at    TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (user_id, gallery_id)
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
CREATE INDEX IF NOT EXISTS idx_download_jobs_user_id ON download_jobs (user_id);

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

-- Image browser columns
ALTER TABLE images ADD COLUMN IF NOT EXISTS added_at TIMESTAMPTZ;
ALTER TABLE blobs ADD COLUMN IF NOT EXISTS thumbhash TEXT;
CREATE INDEX IF NOT EXISTS idx_images_added_at_id ON images (added_at DESC, id DESC);

-- pHash quarter columns for pigeonhole pre-filter (scalability)
ALTER TABLE blobs ADD COLUMN IF NOT EXISTS phash_int BIGINT;
ALTER TABLE blobs ADD COLUMN IF NOT EXISTS phash_q0 SMALLINT;
ALTER TABLE blobs ADD COLUMN IF NOT EXISTS phash_q1 SMALLINT;
ALTER TABLE blobs ADD COLUMN IF NOT EXISTS phash_q2 SMALLINT;
ALTER TABLE blobs ADD COLUMN IF NOT EXISTS phash_q3 SMALLINT;

CREATE INDEX IF NOT EXISTS idx_galleries_library_path ON galleries (library_path);
CREATE INDEX IF NOT EXISTS idx_galleries_last_scanned ON galleries (last_scanned_at NULLS FIRST);

-- ── Plugin Config ────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS plugin_config (
    source_id   TEXT PRIMARY KEY,
    enabled     BOOLEAN DEFAULT TRUE,
    config_json JSONB DEFAULT '{}',
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ── Subscriptions (replaces followed_artists) ──────────────────────

CREATE TABLE IF NOT EXISTS subscriptions (
    id              BIGSERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name            TEXT,
    url             TEXT NOT NULL,
    source          TEXT,
    source_id       TEXT,
    avatar_url      TEXT,
    enabled         BOOLEAN DEFAULT TRUE,
    auto_download   BOOLEAN DEFAULT TRUE,
    cron_expr       TEXT DEFAULT '0 */2 * * *',
    last_checked_at TIMESTAMPTZ,
    last_item_id    TEXT,
    last_status     TEXT DEFAULT 'pending',
    last_error      TEXT,
    next_check_at   TIMESTAMPTZ DEFAULT now(),
    created_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE(user_id, url)
);
CREATE INDEX IF NOT EXISTS idx_subscriptions_next_check ON subscriptions(next_check_at) WHERE enabled = true;
CREATE INDEX IF NOT EXISTS idx_subscriptions_user ON subscriptions(user_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_source ON subscriptions(source, source_id);

-- Artist grouping
ALTER TABLE galleries ADD COLUMN IF NOT EXISTS artist_id TEXT;
CREATE INDEX IF NOT EXISTS idx_galleries_artist_id ON galleries (artist_id) WHERE artist_id IS NOT NULL;

-- ── Audit Logs ────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS audit_logs (
    id              BIGSERIAL PRIMARY KEY,
    user_id         INTEGER REFERENCES users(id) ON DELETE SET NULL,
    action          VARCHAR(100) NOT NULL,
    resource_type   VARCHAR(50),
    resource_id     VARCHAR(100),
    details         JSONB,
    ip_address      INET,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_audit_logs_user_id    ON audit_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at ON audit_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_audit_logs_action     ON audit_logs(action);

-- ── Collections ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS collections (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             BIGINT REFERENCES users(id) ON DELETE CASCADE,
    name                TEXT NOT NULL,
    description         TEXT,
    cover_gallery_id    BIGINT REFERENCES galleries(id) ON DELETE SET NULL,
    created_at          TIMESTAMPTZ DEFAULT now(),
    updated_at          TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS collection_galleries (
    collection_id   BIGINT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    gallery_id      BIGINT NOT NULL REFERENCES galleries(id) ON DELETE CASCADE,
    position        INTEGER DEFAULT 0,
    added_at        TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (collection_id, gallery_id)
);
CREATE INDEX IF NOT EXISTS idx_collection_galleries_gallery ON collection_galleries (gallery_id);

-- ── Excluded Blobs ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS excluded_blobs (
    gallery_id  BIGINT NOT NULL REFERENCES galleries(id) ON DELETE CASCADE,
    blob_sha256 TEXT NOT NULL,
    excluded_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (gallery_id, blob_sha256)
);

-- ── Blob Relationships (dedup pipeline) ──────────────────────────────
CREATE TABLE IF NOT EXISTS blob_relationships (
    id              BIGSERIAL PRIMARY KEY,
    sha_a           TEXT NOT NULL REFERENCES blobs(sha256) ON DELETE CASCADE,
    sha_b           TEXT NOT NULL REFERENCES blobs(sha256) ON DELETE CASCADE,
    hamming_dist    SMALLINT NOT NULL,
    relationship    TEXT NOT NULL DEFAULT 'needs_t2',
    suggested_keep  TEXT,
    reason          TEXT,
    diff_score      FLOAT,
    diff_type       TEXT,
    tier            SMALLINT NOT NULL DEFAULT 1,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_blob_pair UNIQUE (sha_a, sha_b),
    CONSTRAINT chk_canonical_order CHECK (sha_a < sha_b)
);
CREATE INDEX IF NOT EXISTS idx_blob_rel_relationship ON blob_relationships (relationship, id);
CREATE INDEX IF NOT EXISTS idx_blob_rel_sha_a ON blob_relationships (sha_a);
CREATE INDEX IF NOT EXISTS idx_blob_rel_sha_b ON blob_relationships (sha_b);

-- ── Gallery Access Control (prep) ──────────────────────────────────
ALTER TABLE galleries ADD COLUMN IF NOT EXISTS visibility TEXT DEFAULT 'public';
ALTER TABLE galleries ADD COLUMN IF NOT EXISTS created_by_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_galleries_visibility ON galleries (visibility);
CREATE INDEX IF NOT EXISTS idx_galleries_created_by ON galleries (created_by_user_id) WHERE created_by_user_id IS NOT NULL;

-- ── User Favorites ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS user_favorites (
    user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    gallery_id  BIGINT NOT NULL REFERENCES galleries(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (user_id, gallery_id)
);
CREATE INDEX IF NOT EXISTS idx_user_favorites_gallery ON user_favorites (gallery_id);

-- ── User Ratings ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS user_ratings (
    user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    gallery_id  BIGINT NOT NULL REFERENCES galleries(id) ON DELETE CASCADE,
    rating      SMALLINT NOT NULL CHECK (rating >= 0 AND rating <= 5),
    rated_at    TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (user_id, gallery_id)
);
CREATE INDEX IF NOT EXISTS idx_user_ratings_gallery ON user_ratings (gallery_id);

-- ── Download Retry ──────────────────────────────────────────────────
ALTER TABLE download_jobs ADD COLUMN IF NOT EXISTS retry_count SMALLINT DEFAULT 0;
ALTER TABLE download_jobs ADD COLUMN IF NOT EXISTS max_retries SMALLINT DEFAULT 3;
ALTER TABLE download_jobs ADD COLUMN IF NOT EXISTS next_retry_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_download_jobs_retry ON download_jobs (status, retry_count, next_retry_at) WHERE status IN ('failed', 'partial');

-- ── Subscription Batch Tracking ──────────────────────────────────
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS batch_total INT DEFAULT 0;
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS batch_enqueued INT DEFAULT 0;

-- ── Progressive Import: link download_jobs to gallery ────────────
ALTER TABLE download_jobs ADD COLUMN IF NOT EXISTS gallery_id BIGINT REFERENCES galleries(id) ON DELETE SET NULL;

-- ── Source URL ──────────────────────────────────────────────────────
ALTER TABLE galleries ADD COLUMN IF NOT EXISTS source_url TEXT;

-- ── Subscription → Download Job linking ──────────────────────────────
ALTER TABLE download_jobs ADD COLUMN IF NOT EXISTS subscription_id BIGINT REFERENCES subscriptions(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_download_jobs_subscription ON download_jobs(subscription_id) WHERE subscription_id IS NOT NULL;
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS last_job_id UUID REFERENCES download_jobs(id) ON DELETE SET NULL;

-- Soft delete support
ALTER TABLE galleries ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_galleries_deleted_at ON galleries (deleted_at) WHERE deleted_at IS NOT NULL;

-- ── User Image Favorites ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS user_image_favorites (
    user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    image_id    BIGINT NOT NULL REFERENCES images(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (user_id, image_id)
);
CREATE INDEX IF NOT EXISTS idx_uif_image ON user_image_favorites (image_id);

-- ── User Reading List ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS user_reading_list (
    user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    gallery_id  BIGINT NOT NULL REFERENCES galleries(id) ON DELETE CASCADE,
    added_at    TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (user_id, gallery_id)
);
CREATE INDEX IF NOT EXISTS idx_user_reading_list_gallery ON user_reading_list (gallery_id);

-- ── Site Configs (download tuning) ──────────────────────────────────
CREATE TABLE IF NOT EXISTS site_configs (
    source_id   TEXT PRIMARY KEY,
    overrides   JSONB NOT NULL DEFAULT '{}',
    adaptive    JSONB NOT NULL DEFAULT '{}',
    auto_probe  JSONB,
    updated_at  TIMESTAMPTZ DEFAULT now()
);
