#!/usr/bin/env bash
# Jyzrox Database Restore Script
# Usage: ./scripts/restore.sh <backup_file.sql.gz>

set -euo pipefail
trap 'echo "[restore] Error occurred, restarting services..."; docker compose up -d api worker pwa nginx; exit 1' ERR

if [ $# -lt 1 ]; then
  echo "Usage: $0 <backup_file.sql.gz>"
  echo "Available backups:"
  ls -lh backups/vault_*.sql.gz 2>/dev/null || echo "  (none found)"
  exit 1
fi

BACKUP_FILE="$1"
DB_USER="vault"
DB_NAME="vault"

if [ ! -f "$BACKUP_FILE" ]; then
  echo "Error: File not found: $BACKUP_FILE"
  exit 1
fi

echo "WARNING: This will DROP and recreate the '$DB_NAME' database!"
read -p "Are you sure? (yes/no): " CONFIRM
if [ "$CONFIRM" != "yes" ]; then
  echo "Aborted."
  exit 1
fi

echo "[restore] Stopping all services (except postgres)..."
docker compose stop api worker pwa nginx

echo "[restore] Dropping and recreating schema..."
docker compose exec -T postgres \
  psql -U "$DB_USER" -d "$DB_NAME" \
  -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"

echo "[restore] Loading backup data..."
gunzip -c "$BACKUP_FILE" | docker compose exec -T postgres \
  psql -U "$DB_USER" -d "$DB_NAME"

echo "[restore] Restarting all services..."
docker compose up -d api worker pwa nginx
docker compose exec nginx nginx -s reload

echo "[restore] Done!"
