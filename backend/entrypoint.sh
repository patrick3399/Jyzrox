#!/bin/sh
# Entrypoint: ensure data directories are writable by appuser, then exec as appuser.
# PUID/PGID env vars allow dev override (default: 1042:1042 matching appuser in image).
set -e

PUID="${PUID:-1042}"
PGID="${PGID:-1042}"

# Adjust appuser UID/GID if the caller requested a different identity (dev mode).
if [ "$(id -u appuser)" != "$PUID" ] || [ "$(id -g appgroup)" != "$PGID" ]; then
    groupmod -g "$PGID" appgroup
    usermod  -u "$PUID" -g "$PGID" appuser
fi

# Create and fix ownership of bind-mounted data directories.
for dir in /data/gallery /data/thumbs /data/training /data/avatars /data/cas /data/library /app/config; do
    mkdir -p "$dir"
    chown "$PUID:$PGID" "$dir"
done

exec gosu appuser "$@"
