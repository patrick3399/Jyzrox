#!/usr/bin/env bash
# Jyzrox Database Backup Script
# Usage: ./scripts/backup.sh [backup_dir]
#
# Creates a timestamped PostgreSQL dump and optionally compresses it.
# Default backup directory: ./backups/

set -euo pipefail

BACKUP_DIR="${1:-./backups}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Read DB credentials from .env at project root (same directory as docker-compose.yml)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$PROJECT_DIR/.env"
if [ -f "$ENV_FILE" ]; then
  DB_USER="$(grep -E '^POSTGRES_USER=' "$ENV_FILE" | cut -d= -f2- | tr -d '[:space:]')"
  DB_NAME="$(grep -E '^POSTGRES_DB=' "$ENV_FILE" | cut -d= -f2- | tr -d '[:space:]')"
fi
DB_USER="${DB_USER:-vault}"
DB_NAME="${DB_NAME:-vault}"

mkdir -p "$BACKUP_DIR"

# Redis backup
echo "[backup] Triggering Redis BGSAVE..."
docker compose exec -T redis redis-cli BGSAVE 2>/dev/null || true
sleep 2
# Copy Redis dump alongside the DB backup
REDIS_DUMP="${BACKUP_DIR}/redis_${TIMESTAMP}.rdb"
docker compose cp redis:/data/dump.rdb "$REDIS_DUMP" 2>/dev/null || echo "[backup] Warning: Redis dump copy failed"

# Determine output filename and encryption mode
if [ -n "${BACKUP_ENCRYPT_KEY:-}" ]; then
  OUT_FILE="$BACKUP_DIR/vault_$TIMESTAMP.sql.gz.gpg"
  ENCRYPT=1
else
  OUT_FILE="$BACKUP_DIR/vault_$TIMESTAMP.sql.gz"
  ENCRYPT=0
fi

echo "[backup] Starting database backup..."
echo "[backup] Target: $OUT_FILE"
[ "$ENCRYPT" -eq 1 ] && echo "[backup] Encryption: enabled (AES256)"

# Dump, compress, and optionally encrypt in one pipeline
if [ "$ENCRYPT" -eq 1 ]; then
  docker compose exec -T postgres \
    pg_dump -U "$DB_USER" "$DB_NAME" \
    | gzip \
    | gpg --symmetric --cipher-algo AES256 --batch --passphrase "$BACKUP_ENCRYPT_KEY" \
    > "$OUT_FILE"
else
  docker compose exec -T postgres \
    pg_dump -U "$DB_USER" "$DB_NAME" \
    | gzip > "$OUT_FILE"
fi

SIZE=$(du -h "$OUT_FILE" | cut -f1)
echo "[backup] Done! Size: $SIZE"

# Cleanup: keep last 30 backups (handles both plain and encrypted)
KEEP=30
COUNT=$(ls -1 "$BACKUP_DIR"/vault_*.sql.gz* 2>/dev/null | wc -l)
if [ "$COUNT" -gt "$KEEP" ]; then
  REMOVE=$((COUNT - KEEP))
  ls -1t "$BACKUP_DIR"/vault_*.sql.gz* 2>/dev/null | tail -n "$REMOVE" | xargs rm -f
  echo "[backup] Cleaned up $REMOVE old backup(s), keeping last $KEEP"
fi

# Cleanup: keep last 30 Redis RDB files
REDIS_COUNT=$(ls -1 "$BACKUP_DIR"/redis_*.rdb 2>/dev/null | wc -l)
if [ "$REDIS_COUNT" -gt "$KEEP" ]; then
  REDIS_REMOVE=$((REDIS_COUNT - KEEP))
  ls -1t "$BACKUP_DIR"/redis_*.rdb 2>/dev/null \
    | tail -n "$REDIS_REMOVE" | xargs rm -f
  echo "[backup] Cleaned up $REDIS_REMOVE old Redis dump(s), keeping last $KEEP"
fi
