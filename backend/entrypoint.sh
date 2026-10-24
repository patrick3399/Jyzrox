#!/bin/sh
# Entrypoint: ensure data directories are writable by appuser, then exec as appuser.
# PUID/PGID env vars set the runtime identity (default: 1042:1042 matching appuser in image).
set -e

# Warn about insecure .env permissions
if [ -f /app/.env ] && [ "$(stat -c %a /app/.env)" != "600" ]; then
    echo "WARNING: .env file has permissive permissions ($(stat -c %a /app/.env)). Consider chmod 600."
fi

PUID="${PUID:-1042}"
PGID="${PGID:-1042}"

# Adjust appuser UID/GID if PUID/PGID request a different identity.
if [ "$(id -u appuser)" != "$PUID" ] || [ "$(id -g appgroup)" != "$PGID" ]; then
    groupmod -g "$PGID" appgroup
    usermod  -u "$PUID" -g "$PGID" appuser
    # Image files were baked as 1042:1042; re-own them so the new UID can read /app.
    chown -R "$PUID:$PGID" /app /home/appuser 2>/dev/null || true
fi

# Create and fix ownership of bind-mounted data directories.
# Skip read-only mounts (e.g. /opt/gallery-dl:ro on the API container).
for dir in /data/download_temp /data/thumbs /data/training /data/avatars /data/cas /data/library /data/backups /data/archive /app/config /opt/gallery-dl; do
    mkdir -p "$dir" 2>/dev/null || true
    chown "$PUID:$PGID" "$dir" 2>/dev/null || true
done

# Novel module: own the working clone.
mkdir -p /data/novel 2>/dev/null || true
chown -R "$PUID:$PGID" /data/novel 2>/dev/null || true

# Managed SSH identity for the novel hub (named volume, api/worker only).
mkdir -p /var/lib/jyzrox/novel_ssh 2>/dev/null || true
chown -R "$PUID:$PGID" /var/lib/jyzrox/novel_ssh 2>/dev/null || true
chmod 700 /var/lib/jyzrox/novel_ssh 2>/dev/null || true

exec gosu appuser "$@"
