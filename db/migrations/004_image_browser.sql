-- Denormalize added_at from galleries to images (avoids large JOIN)
ALTER TABLE images ADD COLUMN IF NOT EXISTS added_at TIMESTAMPTZ;
UPDATE images SET added_at = g.added_at
  FROM galleries g WHERE images.gallery_id = g.id AND images.added_at IS NULL;
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_images_added_at_id
  ON images (added_at DESC, id DESC);

-- Add thumbhash column to blobs
ALTER TABLE blobs ADD COLUMN IF NOT EXISTS thumbhash TEXT;
