#!/bin/sh
# Entrypoint: ensure data directories are writable by appuser, then exec as appuser.
# PUID/PGID env vars allow dev override (default: 1042:1042 matching appuser in image).
set -e

# Warn about insecure .env permissions
if [ -f /app/.env ] && [ "$(stat -c %a /app/.env)" != "600" ]; then
    echo "WARNING: .env file has permissive permissions ($(stat -c %a /app/.env)). Consider chmod 600."
fi

PUID="${PUID:-1042}"
PGID="${PGID:-1042}"

# Adjust appuser UID/GID if the caller requested a different identity (dev mode).
if [ "$(id -u appuser)" != "$PUID" ] || [ "$(id -g appgroup)" != "$PGID" ]; then
    groupmod -g "$PGID" appgroup
    usermod  -u "$PUID" -g "$PGID" appuser
fi

# Create and fix ownership of bind-mounted data directories.
# Skip read-only mounts (e.g. /opt/gallery-dl:ro on the API container).
for dir in /data/gallery /data/thumbs /data/training /data/avatars /data/cas /data/library /data/archive /app/config /opt/gallery-dl; do
    mkdir -p "$dir" 2>/dev/null || true
    chown "$PUID:$PGID" "$dir" 2>/dev/null || true
done

exec gosu appuser "$@"
