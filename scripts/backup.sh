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

echo "[backup] Starting database backup..."
echo "[backup] Target: $BACKUP_DIR/vault_$TIMESTAMP.sql.gz"

# Dump and compress in one step
docker compose exec -T postgres \
  pg_dump -U "$DB_USER" "$DB_NAME" \
  | gzip > "$BACKUP_DIR/vault_$TIMESTAMP.sql.gz"

SIZE=$(du -h "$BACKUP_DIR/vault_$TIMESTAMP.sql.gz" | cut -f1)
echo "[backup] Done! Size: $SIZE"

# Cleanup: keep last 30 backups
KEEP=30
COUNT=$(ls -1 "$BACKUP_DIR"/vault_*.sql.gz 2>/dev/null | wc -l)
if [ "$COUNT" -gt "$KEEP" ]; then
  REMOVE=$((COUNT - KEEP))
  ls -1t "$BACKUP_DIR"/vault_*.sql.gz | tail -n "$REMOVE" | xargs rm -f
  echo "[backup] Cleaned up $REMOVE old backup(s), keeping last $KEEP"
fi
