#!/usr/bin/env bash
# Jyzrox Database Restore Script
# Usage: ./scripts/restore.sh <backup_file.sql.gz>

set -euo pipefail
trap 'echo "[restore] Error occurred, restarting services..."; docker compose up -d api worker pwa nginx; exit 1' ERR

if [ $# -lt 1 ]; then
  echo "Usage: $0 <backup_file.sql.gz|backup_file.sql.gz.gpg>"
  echo "Available backups:"
  ls -lh backups/vault_*.sql.gz backups/vault_*.sql.gz.gpg 2>/dev/null || echo "  (none found)"
  exit 1
fi

BACKUP_FILE="$1"

# Read DB credentials from .env at project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$PROJECT_DIR/.env"
if [ -f "$ENV_FILE" ]; then
  DB_USER="$(grep -E '^POSTGRES_USER=' "$ENV_FILE" | cut -d= -f2- | tr -d '[:space:]')"
  DB_NAME="$(grep -E '^POSTGRES_DB=' "$ENV_FILE" | cut -d= -f2- | tr -d '[:space:]')"
fi
DB_USER="${DB_USER:-vault}"
DB_NAME="${DB_NAME:-vault}"

# --- 驗證 backup 檔案 ---
if [ ! -f "$BACKUP_FILE" ]; then
  echo "Error: File not found: $BACKUP_FILE"
  exit 1
fi

BACKUP_SIZE=$(stat -c%s "$BACKUP_FILE" 2>/dev/null || stat -f%z "$BACKUP_FILE")
if [ "$BACKUP_SIZE" -eq 0 ]; then
  echo "Error: Backup file is empty: $BACKUP_FILE"
  exit 1
fi

echo ""
echo "============================================"
echo "  Jyzrox Database Restore"
echo "============================================"
echo "  Restore from : $(basename "$BACKUP_FILE")"
echo "  File size    : $(du -sh "$BACKUP_FILE" | cut -f1)"
echo "  Target DB    : $DB_NAME"
echo "============================================"
echo ""
echo "WARNING: This will DROP and recreate the '$DB_NAME' database!"
echo "All existing data will be permanently lost."
echo ""
read -rp "Type YES (all caps) to confirm: " CONFIRM
if [ "$CONFIRM" != "YES" ]; then
  echo "Aborted."
  exit 1
fi

# --- 自動備份當前資料庫（安全網）---
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
if [ -n "${BACKUP_ENCRYPT_KEY:-}" ]; then
  SAFETY_BACKUP="backups/pre_restore_${TIMESTAMP}.sql.gz.gpg"
else
  SAFETY_BACKUP="backups/pre_restore_${TIMESTAMP}.sql.gz"
fi
mkdir -p backups
echo "[restore] Creating safety backup of current database → $SAFETY_BACKUP ..."
if [ -n "${BACKUP_ENCRYPT_KEY:-}" ]; then
  docker compose exec -T postgres \
    pg_dump -U "$DB_USER" "$DB_NAME" \
    | gzip \
    | gpg --symmetric --cipher-algo AES256 --batch --passphrase "$BACKUP_ENCRYPT_KEY" \
    > "$SAFETY_BACKUP"
else
  docker compose exec -T postgres \
    pg_dump -U "$DB_USER" "$DB_NAME" | gzip > "$SAFETY_BACKUP"
fi

# 驗證 safety backup 非空
SAFETY_SIZE=$(stat -c%s "$SAFETY_BACKUP" 2>/dev/null || stat -f%z "$SAFETY_BACKUP")
if [ "$SAFETY_SIZE" -eq 0 ]; then
  echo "Error: Safety backup failed (empty file). Aborting restore."
  rm -f "$SAFETY_BACKUP"
  exit 1
fi
echo "[restore] Safety backup OK ($(du -sh "$SAFETY_BACKUP" | cut -f1))"

echo "[restore] Stopping all services (except postgres)..."
docker compose stop api worker pwa nginx

echo "[restore] Dropping and recreating schema..."
docker compose exec -T postgres \
  psql -U "$DB_USER" -d "$DB_NAME" \
  -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"

echo "[restore] Loading backup data..."
if [[ "$BACKUP_FILE" == *.gpg ]]; then
  if [ -z "${BACKUP_ENCRYPT_KEY:-}" ]; then
    echo "Error: Backup file is GPG-encrypted but BACKUP_ENCRYPT_KEY is not set."
    exit 1
  fi
  echo "[restore] Decrypting backup (AES256)..."
  gpg --decrypt --batch --passphrase "$BACKUP_ENCRYPT_KEY" "$BACKUP_FILE" \
    | gunzip \
    | docker compose exec -T postgres \
      psql -U "$DB_USER" -d "$DB_NAME" --single-transaction
else
  gunzip -c "$BACKUP_FILE" | docker compose exec -T postgres \
    psql -U "$DB_USER" -d "$DB_NAME" --single-transaction
fi

echo "[restore] Restarting all services..."
docker compose up -d api worker pwa nginx
docker compose exec nginx nginx -s reload

echo ""
echo "[restore] Done!"
echo "[restore] Safety backup retained at: $SAFETY_BACKUP"
echo "[restore] If anything looks wrong, restore from the safety backup:"
echo "          $0 $SAFETY_BACKUP"
