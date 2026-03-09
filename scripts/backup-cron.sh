#!/usr/bin/env bash
# Jyzrox Backup Cron Wrapper
#
# Wraps backup.sh with logging. Designed to be called from cron or a systemd timer.
#
# ── Cron setup (run as the user who owns the project) ──────────────────────
#
#   Edit crontab with:  crontab -e
#
#   Daily at 03:00:
#     0 3 * * * /home/patrick339/Jyzrox/scripts/backup-cron.sh
#
#   Or weekly on Sunday at 02:30:
#     30 2 * * 0 /home/patrick339/Jyzrox/scripts/backup-cron.sh
#
# ── systemd timer setup (alternative to cron) ──────────────────────────────
#
#   1. Copy the two unit files below to /etc/systemd/system/ (or ~/.config/systemd/user/)
#
#   /etc/systemd/system/jyzrox-backup.service
#   ------------------------------------------
#   [Unit]
#   Description=Jyzrox database backup
#   After=docker.service
#
#   [Service]
#   Type=oneshot
#   User=patrick339
#   ExecStart=/home/patrick339/Jyzrox/scripts/backup-cron.sh
#
#   /etc/systemd/system/jyzrox-backup.timer
#   -----------------------------------------
#   [Unit]
#   Description=Run Jyzrox backup daily at 03:00
#
#   [Timer]
#   OnCalendar=*-*-* 03:00:00
#   Persistent=true
#
#   [Install]
#   WantedBy=timers.target
#
#   2. Enable and start:
#      sudo systemctl daemon-reload
#      sudo systemctl enable --now jyzrox-backup.timer
#
#   3. Check status:
#      sudo systemctl list-timers jyzrox-backup.timer
#      sudo journalctl -u jyzrox-backup.service --since today
#
# ───────────────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BACKUP_DIR="$PROJECT_DIR/backups"
LOG_DIR="$PROJECT_DIR/backups/logs"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="$LOG_DIR/backup_${TIMESTAMP}.log"

mkdir -p "$LOG_DIR"

echo "[backup-cron] $(date '+%Y-%m-%d %H:%M:%S') — starting backup" | tee -a "$LOG_FILE"

# Run backup.sh from the project directory so docker compose finds docker-compose.yml
cd "$PROJECT_DIR"
"$SCRIPT_DIR/backup.sh" "$BACKUP_DIR" 2>&1 | tee -a "$LOG_FILE"

EXIT_CODE=${PIPESTATUS[0]}

if [ "$EXIT_CODE" -eq 0 ]; then
  echo "[backup-cron] $(date '+%Y-%m-%d %H:%M:%S') — backup completed successfully" | tee -a "$LOG_FILE"
else
  echo "[backup-cron] $(date '+%Y-%m-%d %H:%M:%S') — backup FAILED (exit $EXIT_CODE)" | tee -a "$LOG_FILE"
fi

# Keep last 90 log files
LOG_COUNT=$(ls -1 "$LOG_DIR"/backup_*.log 2>/dev/null | wc -l)
KEEP_LOGS=90
if [ "$LOG_COUNT" -gt "$KEEP_LOGS" ]; then
  REMOVE=$((LOG_COUNT - KEEP_LOGS))
  ls -1t "$LOG_DIR"/backup_*.log | tail -n "$REMOVE" | xargs rm -f
fi

exit "$EXIT_CODE"
