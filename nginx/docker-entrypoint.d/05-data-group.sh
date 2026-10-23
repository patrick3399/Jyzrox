#!/bin/sh
# Let the nginx worker read the data volume when its owner group is PGID.
# The volume is chmod 770 (no "other" access), and the worker runs as the
# image's nginx user, so it must join the group that owns the files.
set -e

PGID="${PGID:-}"
[ -n "$PGID" ] || exit 0

group="$(getent group "$PGID" | cut -d: -f1 || true)"
if [ -z "$group" ]; then
    group="jyzrox-data"
    addgroup -g "$PGID" "$group"
fi
addgroup nginx "$group" 2>/dev/null || true
echo "05-data-group: nginx joined group $group ($PGID)"
