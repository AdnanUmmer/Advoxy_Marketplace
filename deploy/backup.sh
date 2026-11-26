#!/usr/bin/env bash
# Nightly PostgreSQL backup (installed by provision.sh as /usr/local/bin/advoxy-backup, run by cron).
# Keeps 14 daily dumps. Uploaded photos live in /srv/advoxy/media and licence files in
# /srv/advoxy/private_media: include both folders in your VPS snapshot or off-site copy.
set -euo pipefail

DIR="${BACKUP_DIR:-/srv/advoxy/backups}"
KEEP_DAYS="${KEEP_DAYS:-14}"
STAMP=$(date +%Y-%m-%d_%H%M)
FILE="$DIR/advoxy_$STAMP.dump"

mkdir -p "$DIR"
# Custom format: compressed, and restorable table by table with pg_restore.
pg_dump --format=custom --no-owner --dbname=advoxy --file="$FILE.part"
mv "$FILE.part" "$FILE"
chmod 600 "$FILE"
find "$DIR" -name 'advoxy_*.dump' -mtime "+$KEEP_DAYS" -delete
echo "$(date -Is) backup ok: $FILE ($(du -h "$FILE" | cut -f1))"

# Restore (into an empty database with PostGIS enabled):
#   pg_restore --no-owner --dbname=advoxy /srv/advoxy/backups/advoxy_YYYY-MM-DD_HHMM.dump
