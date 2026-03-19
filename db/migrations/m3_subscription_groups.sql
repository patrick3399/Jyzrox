-- M3: Subscription Groups — Idempotent Migration
-- Run with: psql -f db/migrations/m3_subscription_groups.sql

BEGIN;

-- 1. Create subscription_groups table
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

-- 2. Seed Default system group (idempotent)
INSERT INTO subscription_groups (name, schedule, concurrency, priority, is_system)
SELECT 'Default', '0 */2 * * *', 2, 3, true
WHERE NOT EXISTS (
    SELECT 1 FROM subscription_groups WHERE is_system = true AND name = 'Default'
);

-- 3. Add group_id FK to subscriptions
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS group_id INT
    REFERENCES subscription_groups(id) ON DELETE SET NULL;

-- 4. Index for group lookups
CREATE INDEX IF NOT EXISTS idx_subscriptions_group ON subscriptions(group_id);

-- 5. Assign existing subscriptions to Default group
UPDATE subscriptions
SET group_id = (SELECT id FROM subscription_groups WHERE is_system = true AND name = 'Default' LIMIT 1)
WHERE group_id IS NULL;

COMMIT;
