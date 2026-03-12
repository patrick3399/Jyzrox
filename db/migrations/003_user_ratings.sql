-- Migration: Per-user ratings
-- Date: 2026-03-12

CREATE TABLE IF NOT EXISTS user_ratings (
    user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    gallery_id BIGINT NOT NULL REFERENCES galleries(id) ON DELETE CASCADE,
    rating     SMALLINT NOT NULL CHECK (rating >= 0 AND rating <= 5),
    rated_at   TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (user_id, gallery_id)
);

-- Migrate existing global ratings to first admin user
INSERT INTO user_ratings (user_id, gallery_id, rating)
SELECT (SELECT id FROM users WHERE role = 'admin' ORDER BY id LIMIT 1), id, rating
FROM galleries
WHERE rating > 0
ON CONFLICT DO NOTHING;
