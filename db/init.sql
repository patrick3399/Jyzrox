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
    locale          TEXT,
    ui_preferences  JSONB NOT NULL DEFAULT '{}'::jsonb
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
    source_pages    INT,
    posted_at       TIMESTAMPTZ,
    added_at        TIMESTAMPTZ DEFAULT now(),
    rating          SMALLINT DEFAULT 0,
    favorited       BOOLEAN DEFAULT false,
    uploader        TEXT,
    download_status TEXT DEFAULT 'proxy_only',
    import_mode     TEXT,
    source_path     TEXT,
    tags_array      TEXT[] DEFAULT '{}',
    source_url      TEXT,
    metadata_updated_at TIMESTAMPTZ,
    UNIQUE (source, source_id)
);

DO $$ BEGIN
    ALTER TABLE galleries ADD CONSTRAINT chk_galleries_source_pages_nonnegative
        CHECK (source_pages IS NULL OR source_pages >= 0);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

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
    dedup_scanned_threshold SMALLINT,
    dedup_scanned_phash_int BIGINT,
    dedup_scanned_version SMALLINT,
    occurrence_revision BIGINT NOT NULL DEFAULT 0,
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
CREATE INDEX IF NOT EXISTS idx_blobs_dedup_scanned_threshold
    ON blobs(dedup_scanned_threshold) WHERE phash_int IS NOT NULL;

CREATE TABLE IF NOT EXISTS blob_locations (
    blob_sha256  TEXT NOT NULL REFERENCES blobs(sha256) ON DELETE CASCADE,
    external_path TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (blob_sha256, external_path)
);

CREATE TABLE IF NOT EXISTS images (
    id              BIGSERIAL PRIMARY KEY,
    gallery_id      BIGINT NOT NULL REFERENCES galleries(id) ON DELETE CASCADE,
    page_num        INT NOT NULL,
    filename        TEXT,
    blob_sha256     TEXT NOT NULL REFERENCES blobs(sha256),
    external_path   TEXT,
    caption         TEXT,
    visibility      TEXT NOT NULL DEFAULT 'active',
    source_item_id  TEXT,
    source_item_url TEXT,
    source_position INT,
    source_seen_at  TIMESTAMPTZ,
    hidden_at       TIMESTAMPTZ,
    replaced_by_image_id BIGINT REFERENCES images(id) ON DELETE SET NULL,
    CONSTRAINT fk_images_blob_location
        FOREIGN KEY (blob_sha256, external_path)
        REFERENCES blob_locations(blob_sha256, external_path),
    UNIQUE (gallery_id, page_num)
);
CREATE INDEX IF NOT EXISTS idx_images_external_path
    ON images(external_path) WHERE external_path IS NOT NULL;

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

CREATE SEQUENCE IF NOT EXISTS download_admission_ticket_seq;

CREATE TABLE IF NOT EXISTS download_jobs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    url             TEXT NOT NULL,
    canonical_url   TEXT,
    source          TEXT,
    status          TEXT DEFAULT 'queued',
    progress        JSONB DEFAULT '{}',
    options         JSONB DEFAULT '{}',
    error           TEXT,
    created_at      TIMESTAMPTZ DEFAULT now(),
    finished_at     TIMESTAMPTZ,
    user_id         BIGINT REFERENCES users(id) ON DELETE SET NULL,
    admission_key   TEXT,
    admission_token UUID,
    admission_ticket BIGINT DEFAULT nextval('download_admission_ticket_seq')
);

CREATE TABLE IF NOT EXISTS read_progress (
    user_id         BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    gallery_id      BIGINT NOT NULL REFERENCES galleries(id) ON DELETE CASCADE,
    last_page       INT DEFAULT 0,
    last_read_at    TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (user_id, gallery_id)
);

CREATE TABLE IF NOT EXISTS workbench_operations (
    id              UUID PRIMARY KEY DEFAULT uuidv7(),
    user_id         BIGINT REFERENCES users(id) ON DELETE SET NULL,
    kind            TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'queued'
                    CHECK (status IN ('queued', 'running', 'completed', 'failed', 'cancelled')),
    selection_count INT NOT NULL DEFAULT 0,
    progress        JSONB NOT NULL DEFAULT '{}',
    params          JSONB NOT NULL DEFAULT '{}',
    error           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS gallery_metadata_field_states (
    gallery_id      BIGINT NOT NULL REFERENCES galleries(id) ON DELETE CASCADE,
    field_name      TEXT NOT NULL,
    origin          TEXT NOT NULL DEFAULT 'source'
                    CHECK (origin IN ('source', 'import', 'manual', 'merge')),
    locked          BOOLEAN NOT NULL DEFAULT false,
    source_value    JSONB,
    updated_by_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (gallery_id, field_name)
);

CREATE TABLE IF NOT EXISTS gallery_metadata_changes (
    id              BIGSERIAL PRIMARY KEY,
    gallery_id      BIGINT NOT NULL REFERENCES galleries(id) ON DELETE CASCADE,
    field_name      TEXT NOT NULL,
    old_value       JSONB,
    new_value       JSONB,
    origin          TEXT NOT NULL CHECK (origin IN ('source', 'import', 'manual', 'merge')),
    actor_user_id   BIGINT REFERENCES users(id) ON DELETE SET NULL,
    operation_id    UUID REFERENCES workbench_operations(id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_workbench_operations_user_id
  ON workbench_operations (user_id);
CREATE INDEX IF NOT EXISTS ix_gallery_metadata_changes_gallery_created
  ON gallery_metadata_changes (gallery_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_gallery_metadata_changes_operation_id
  ON gallery_metadata_changes (operation_id);

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
CREATE INDEX IF NOT EXISTS idx_galleries_title_trgm ON galleries USING GIN (title gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_galleries_title_jpn_trgm ON galleries USING GIN (title_jpn gin_trgm_ops);

-- ── Regular Indexes ──────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_galleries_source    ON galleries (source, source_id);
CREATE INDEX IF NOT EXISTS idx_galleries_added_at  ON galleries (added_at DESC);
CREATE INDEX IF NOT EXISTS idx_images_gallery      ON images (gallery_id, page_num);
CREATE INDEX IF NOT EXISTS idx_images_blob         ON images (blob_sha256);
CREATE INDEX IF NOT EXISTS idx_images_visibility   ON images (visibility);
CREATE INDEX IF NOT EXISTS idx_images_source_item  ON images (gallery_id, source_item_id);

-- #4: galleries.source (single-column) — used in WHERE source = 'pixiv' filters
-- Note: idx_galleries_source above covers (source, source_id); this covers source-only lookups.
CREATE INDEX IF NOT EXISTS idx_galleries_source_only ON galleries (source);

-- #5: tags.count DESC — used in ORDER BY count DESC for tag listing
CREATE INDEX IF NOT EXISTS idx_tags_count ON tags (count DESC);

-- #6: tags.name — UNIQUE (namespace, name) index doesn't cover name-only lookups
--     (name is the second column), so WHERE name = '...' needs this dedicated index.
CREATE INDEX IF NOT EXISTS idx_tags_name ON tags (name);

CREATE INDEX IF NOT EXISTS idx_gallery_tags_tag ON gallery_tags (tag_id);
CREATE INDEX IF NOT EXISTS idx_download_jobs_status ON download_jobs (status);
CREATE INDEX IF NOT EXISTS idx_download_jobs_user_id ON download_jobs (user_id);
ALTER TABLE download_jobs ADD COLUMN IF NOT EXISTS admission_key TEXT;
ALTER TABLE download_jobs ADD COLUMN IF NOT EXISTS admission_token UUID;
ALTER TABLE download_jobs ADD COLUMN IF NOT EXISTS admission_ticket BIGINT
    DEFAULT nextval('download_admission_ticket_seq');
WITH ranked AS (
    SELECT id, row_number() OVER (ORDER BY created_at, id) AS ticket
    FROM download_jobs
    WHERE admission_ticket IS NULL
)
UPDATE download_jobs AS job
SET admission_ticket = ranked.ticket
FROM ranked
WHERE job.id = ranked.id;
SELECT setval(
    'download_admission_ticket_seq',
    GREATEST(COALESCE((SELECT max(admission_ticket) FROM download_jobs), 0), 1),
    EXISTS (SELECT 1 FROM download_jobs)
);
CREATE INDEX IF NOT EXISTS idx_download_jobs_admission_fifo
    ON download_jobs (admission_key, admission_ticket, id)
    WHERE status = 'queued' AND admission_token IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_download_jobs_admission_token
    ON download_jobs (admission_token) WHERE admission_token IS NOT NULL;
ALTER TABLE download_jobs ADD COLUMN IF NOT EXISTS canonical_url TEXT;
UPDATE download_jobs
SET canonical_url = regexp_replace(split_part(btrim(url), '#', 1), '/+$', '')
WHERE canonical_url IS NULL;
WITH ranked AS (
    SELECT id,
           row_number() OVER (
               PARTITION BY user_id, canonical_url
               ORDER BY created_at, id
           ) AS duplicate_rank
    FROM download_jobs
    WHERE user_id IS NOT NULL
      AND canonical_url IS NOT NULL
      AND status IN ('queued', 'running', 'paused')
)
UPDATE download_jobs AS job
SET status = 'failed',
    error = COALESCE(job.error, 'Superseded duplicate active job during canonical URL migration'),
    finished_at = COALESCE(job.finished_at, now())
FROM ranked
WHERE job.id = ranked.id
  AND ranked.duplicate_rank > 1;
CREATE UNIQUE INDEX IF NOT EXISTS uq_download_jobs_active_canonical
    ON download_jobs (user_id, canonical_url)
    WHERE user_id IS NOT NULL
      AND canonical_url IS NOT NULL
      AND status IN ('queued', 'running', 'paused');

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
    pattern     TEXT NOT NULL DEFAULT '{title}',
    import_mode TEXT NOT NULL DEFAULT 'link',
    enabled     BOOLEAN NOT NULL DEFAULT TRUE,
    monitor     BOOLEAN NOT NULL DEFAULT TRUE,
    added_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Gallery extensions for library management
ALTER TABLE galleries ADD COLUMN IF NOT EXISTS last_scanned_at TIMESTAMPTZ;
ALTER TABLE galleries ADD COLUMN IF NOT EXISTS library_path TEXT;
ALTER TABLE galleries ADD COLUMN IF NOT EXISTS source_path TEXT;
ALTER TABLE library_paths ADD COLUMN IF NOT EXISTS pattern TEXT NOT NULL DEFAULT '{title}';
ALTER TABLE library_paths ADD COLUMN IF NOT EXISTS import_mode TEXT NOT NULL DEFAULT 'link';

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

-- ── Subscription Groups ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS subscription_groups (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    schedule        TEXT NOT NULL DEFAULT '0 */6 * * *',
    concurrency     SMALLINT DEFAULT 2,
    enabled         BOOLEAN DEFAULT true,
    priority        SMALLINT DEFAULT 5,
    is_system       BOOLEAN DEFAULT false,
    status          TEXT DEFAULT 'idle',
    last_run_at     TIMESTAMPTZ,
    last_completed_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

-- Seed Default group
INSERT INTO subscription_groups (name, schedule, concurrency, priority, is_system)
SELECT 'Default', '0 */2 * * *', 2, 3, true
WHERE NOT EXISTS (SELECT 1 FROM subscription_groups WHERE is_system = true AND name = 'Default');

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
    download_options JSONB DEFAULT '{}',
    cron_expr       TEXT DEFAULT '0 */2 * * *',
    last_checked_at TIMESTAMPTZ,
    last_success_at TIMESTAMPTZ,
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
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS group_id INT REFERENCES subscription_groups(id) ON DELETE SET NULL;
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS download_options JSONB DEFAULT '{}';
ALTER TABLE download_jobs ADD COLUMN IF NOT EXISTS options JSONB DEFAULT '{}';
CREATE INDEX IF NOT EXISTS idx_subscriptions_group ON subscriptions(group_id);

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

-- ── AI Training Datasets ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS datasets (
    id              BIGSERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    description     TEXT,
    selection_spec  JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_datasets_user_updated ON datasets (user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS dataset_images (
    dataset_id  BIGINT NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    image_id    BIGINT NOT NULL REFERENCES images(id) ON DELETE CASCADE,
    state       TEXT NOT NULL DEFAULT 'included',
    source      TEXT NOT NULL DEFAULT 'manual',
    exclusion_reason TEXT,
    added_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (dataset_id, image_id),
    CONSTRAINT ck_dataset_image_state CHECK (state IN ('included', 'excluded'))
);
CREATE INDEX IF NOT EXISTS ix_dataset_images_image_id ON dataset_images (image_id);

CREATE TABLE IF NOT EXISTS gallery_permissions (
    gallery_id BIGINT NOT NULL REFERENCES galleries(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    can_edit BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (gallery_id, user_id)
);

CREATE TABLE IF NOT EXISTS gallery_share_links (
    id BIGSERIAL PRIMARY KEY,
    gallery_id BIGINT NOT NULL REFERENCES galleries(id) ON DELETE CASCADE,
    created_by_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    expires_at TIMESTAMPTZ,
    filter_r18 BOOLEAN NOT NULL DEFAULT true,
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_gallery_share_links_gallery ON gallery_share_links (gallery_id);

CREATE TABLE IF NOT EXISTS gallery_versions (
    gallery_id BIGINT PRIMARY KEY REFERENCES galleries(id) ON DELETE CASCADE,
    group_id TEXT NOT NULL,
    linked_by_user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    linked_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_gallery_versions_group ON gallery_versions (group_id);

CREATE TABLE IF NOT EXISTS import_conflicts (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    existing_gallery_id BIGINT REFERENCES galleries(id) ON DELETE SET NULL,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    incoming_payload JSONB NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',
    resolution TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at TIMESTAMPTZ,
    CONSTRAINT ck_import_conflict_status CHECK (status IN ('pending', 'resolved'))
);
CREATE INDEX IF NOT EXISTS ix_import_conflicts_user_status ON import_conflicts (user_id, status);

CREATE TABLE IF NOT EXISTS read_events (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    gallery_id BIGINT NOT NULL REFERENCES galleries(id) ON DELETE CASCADE,
    image_id BIGINT REFERENCES images(id) ON DELETE SET NULL,
    page_num INTEGER NOT NULL,
    duration_ms INTEGER,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_read_events_user_time ON read_events (user_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS ix_read_events_gallery ON read_events (gallery_id);

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
    relationship    TEXT NOT NULL DEFAULT 'needs_context',
    suggested_keep  TEXT,
    reason          TEXT,
    diff_score      FLOAT,
    diff_type       TEXT,
    context_scope   TEXT,
    context_revision_a BIGINT,
    context_revision_b BIGINT,
    decision        TEXT,
    decision_keep_sha TEXT,
    decision_by_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    decided_at      TIMESTAMPTZ,
    tier            SMALLINT NOT NULL DEFAULT 1,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_blob_pair UNIQUE (sha_a, sha_b),
    CONSTRAINT chk_canonical_order CHECK (sha_a < sha_b)
);
CREATE INDEX IF NOT EXISTS idx_blob_rel_relationship ON blob_relationships (relationship, id);
CREATE INDEX IF NOT EXISTS idx_blob_rel_sha_a ON blob_relationships (sha_a);
CREATE INDEX IF NOT EXISTS idx_blob_rel_sha_b ON blob_relationships (sha_b);

CREATE OR REPLACE FUNCTION bump_blob_occurrence_revision()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        UPDATE blobs SET occurrence_revision = occurrence_revision + 1 WHERE sha256 = NEW.blob_sha256;
        RETURN NEW;
    ELSIF TG_OP = 'DELETE' THEN
        UPDATE blobs SET occurrence_revision = occurrence_revision + 1 WHERE sha256 = OLD.blob_sha256;
        RETURN OLD;
    END IF;
    IF OLD.blob_sha256 IS DISTINCT FROM NEW.blob_sha256 THEN
        UPDATE blobs SET occurrence_revision = occurrence_revision + 1
        WHERE sha256 IN (OLD.blob_sha256, NEW.blob_sha256);
    ELSIF OLD.gallery_id IS DISTINCT FROM NEW.gallery_id THEN
        UPDATE blobs SET occurrence_revision = occurrence_revision + 1 WHERE sha256 = NEW.blob_sha256;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_images_blob_occurrence_revision ON images;
CREATE TRIGGER trg_images_blob_occurrence_revision
AFTER INSERT OR DELETE OR UPDATE OF blob_sha256, gallery_id ON images
FOR EACH ROW EXECUTE FUNCTION bump_blob_occurrence_revision();

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

-- ── gallery-dl archive tables (v3.0) ────────────────────────────────
-- gallery-dl only reads/writes the 'entry' column.
-- Jyzrox adds gallery_id FK for CASCADE lifecycle management.
-- Tables are named by gallery-dl category (archive-table: "{category}").

CREATE TABLE IF NOT EXISTS exhentai (
    entry       TEXT PRIMARY KEY,
    gallery_id  BIGINT REFERENCES galleries(id) ON DELETE CASCADE,
    job_id      UUID,
    created_at  TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_exhentai_unlinked ON exhentai (job_id) WHERE gallery_id IS NULL;

CREATE TABLE IF NOT EXISTS pixiv (
    entry       TEXT PRIMARY KEY,
    gallery_id  BIGINT REFERENCES galleries(id) ON DELETE CASCADE,
    job_id      UUID,
    created_at  TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_pixiv_unlinked ON pixiv (job_id) WHERE gallery_id IS NULL;

CREATE TABLE IF NOT EXISTS twitter (
    entry       TEXT PRIMARY KEY,
    gallery_id  BIGINT REFERENCES galleries(id) ON DELETE CASCADE,
    job_id      UUID,
    created_at  TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_twitter_unlinked ON twitter (job_id) WHERE gallery_id IS NULL;

CREATE TABLE IF NOT EXISTS instagram (
    entry       TEXT PRIMARY KEY,
    gallery_id  BIGINT REFERENCES galleries(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS danbooru (
    entry       TEXT PRIMARY KEY,
    gallery_id  BIGINT REFERENCES galleries(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS gelbooru (
    entry       TEXT PRIMARY KEY,
    gallery_id  BIGINT REFERENCES galleries(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS newgrounds (
    entry       TEXT PRIMARY KEY,
    gallery_id  BIGINT REFERENCES galleries(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS nijie (
    entry       TEXT PRIMARY KEY,
    gallery_id  BIGINT REFERENCES galleries(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS kemono (
    entry       TEXT PRIMARY KEY,
    gallery_id  BIGINT REFERENCES galleries(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS nhentai (
    entry       TEXT PRIMARY KEY,
    gallery_id  BIGINT REFERENCES galleries(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS hitomi (
    entry       TEXT PRIMARY KEY,
    gallery_id  BIGINT REFERENCES galleries(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS rule34 (
    entry       TEXT PRIMARY KEY,
    gallery_id  BIGINT REFERENCES galleries(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS weibo (
    entry       TEXT PRIMARY KEY,
    gallery_id  BIGINT REFERENCES galleries(id) ON DELETE CASCADE,
    job_id      UUID,
    created_at  TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_weibo_unlinked ON weibo (job_id) WHERE gallery_id IS NULL;

-- ── Performance indexes (benchmark-driven) ─────────────────────────────

-- Image composite: serves browse_images ORDER BY added_at DESC when filtered by gallery_id
CREATE INDEX IF NOT EXISTS idx_images_gallery_added_at_id
  ON images (gallery_id, added_at DESC, id DESC);

-- Gallery partial indexes: avoid scanning deleted rows in common listing queries
CREATE INDEX IF NOT EXISTS idx_galleries_live_added_at_id
  ON galleries (added_at DESC, id DESC)
  WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_galleries_public_added_at_id
  ON galleries (added_at DESC, id DESC)
  WHERE deleted_at IS NULL AND visibility = 'public';

CREATE INDEX IF NOT EXISTS idx_galleries_owner_added_at_id
  ON galleries (created_by_user_id, added_at DESC, id DESC)
  WHERE deleted_at IS NULL AND created_by_user_id IS NOT NULL;

-- ── read_progress indexes (#144) ─────────────────────────────────────
-- read_progress PK is (user_id, gallery_id) — but "recent reads by user"
-- and "recent reads of a gallery" queries filter on a single column, which
-- the composite PK index cannot satisfy without a full scan.
CREATE INDEX IF NOT EXISTS idx_read_progress_user
  ON read_progress (user_id, last_read_at DESC);
CREATE INDEX IF NOT EXISTS idx_read_progress_gallery
  ON read_progress (gallery_id, last_read_at DESC);

-- ── users.role constraint (#190) ──────────────────────────────────────
-- Prevent arbitrary strings from being written into users.role.
-- Valid values mirror ROLE_HIERARCHY in core/auth.py.
-- PostgreSQL has no `ADD CONSTRAINT IF NOT EXISTS`; guard via pg_constraint so
-- this script stays idempotent (re-runnable by scripts/bootstrap_db.py).
DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'chk_users_role'
  ) THEN
    ALTER TABLE users ADD CONSTRAINT chk_users_role
      CHECK (role IN ('admin', 'member', 'viewer'));
  END IF;
END $$;

-- ── Novel module ───────────────────────────────────────────────────────
-- Markdown files are the source of truth; the DB stores only per-user state.
ALTER TABLE users ADD COLUMN IF NOT EXISTS novel_prefs JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE users ADD COLUMN IF NOT EXISTS ui_preferences JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE TABLE IF NOT EXISTS novel_read_progress (
    user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    file_path  TEXT   NOT NULL,          -- repo-relative path
    position   TEXT   NOT NULL,          -- in-chapter anchor (act index + paragraph offset)
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, file_path)
);

-- Knowledge index (Phase 1 Track A): derived, rebuildable from the working tree.
CREATE TABLE IF NOT EXISTS novel_notes (
    file_path   TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    note_type   TEXT,
    aliases     TEXT[] NOT NULL DEFAULT '{}',
    frontmatter JSONB NOT NULL DEFAULT '{}',
    indexed_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS novel_links (
    src_path  TEXT NOT NULL,
    dst_title TEXT NOT NULL,
    dst_path  TEXT,
    PRIMARY KEY (src_path, dst_title)
);
CREATE TABLE IF NOT EXISTS novel_mentions (
    note_path     TEXT NOT NULL,
    chapter_path  TEXT NOT NULL,
    mention_count INT  NOT NULL,
    first_offset  INT  NOT NULL,
    PRIMARY KEY (note_path, chapter_path)
);
CREATE INDEX IF NOT EXISTS idx_novel_notes_type ON novel_notes (note_type);
CREATE INDEX IF NOT EXISTS idx_novel_mentions_note ON novel_mentions (note_path);

-- ── PostgreSQL 18 features ─────────────────────────────────────────────

-- UUIDv7: timestamp-ordered UUIDs for better B-tree index write performance
ALTER TABLE download_jobs ALTER COLUMN id SET DEFAULT uuidv7();
ALTER TABLE api_tokens ALTER COLUMN id SET DEFAULT uuidv7();
