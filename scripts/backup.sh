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
  REDIS_PASSWORD="$(grep -E '^REDIS_PASSWORD=' "$ENV_FILE" | cut -d= -f2- | tr -d '[:space:]')" || true
fi
DB_USER="${DB_USER:-vault}"
DB_NAME="${DB_NAME:-vault}"

mkdir -p "$BACKUP_DIR"

# Redis backup.
# Automatic RDB save points are disabled (see the redis service command), so this
# BGSAVE is the only thing that refreshes /data/dump.rdb. If it fails, dump.rdb is
# stale by an unbounded amount -- skip the copy rather than archive a stale file.
REDIS_CLI=(docker compose exec -T redis redis-cli --no-auth-warning)
[ -n "${REDIS_PASSWORD:-}" ] && REDIS_CLI+=(-a "$REDIS_PASSWORD") || true
REDIS_DUMP="${BACKUP_DIR}/redis_${TIMESTAMP}.rdb"

echo "[backup] Triggering Redis BGSAVE..."
BGSAVE_OUT="$("${REDIS_CLI[@]}" BGSAVE 2>&1 || true)"
if [[ "$BGSAVE_OUT" == *"Background saving started"* \
   || "$BGSAVE_OUT" == *"Background saving scheduled"* ]]; then
  # dump.rdb is only safe to copy once the forked child has finished writing it.
  for _ in $(seq 1 120); do
    IN_PROGRESS="$("${REDIS_CLI[@]}" INFO persistence 2>/dev/null \
      | tr -d '\r' | awk -F: '/^rdb_bgsave_in_progress:/{print $2}' || true)"
    if [ "$IN_PROGRESS" = "0" ]; then break; fi
    sleep 1
  done
  if [ "${IN_PROGRESS:-1}" != "0" ]; then
    echo "[backup] Warning: Redis BGSAVE did not finish in 120s, skipping dump copy"
  else
    docker compose cp redis:/data/dump.rdb "$REDIS_DUMP" \
      || echo "[backup] Warning: Redis dump copy failed"
  fi
else
  echo "[backup] Warning: Redis BGSAVE failed ($BGSAVE_OUT), skipping stale dump.rdb copy"
fi

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
