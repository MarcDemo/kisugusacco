#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$PROJECT_DIR/.env}"

if [ -f "$ENV_FILE" ]; then
  set -a
  . "$ENV_FILE"
  set +a
fi

MEDIA_SOURCE="${DJANGO_MEDIA_ROOT:-$PROJECT_DIR/media}"
BACKUP_DIR="${BACKUP_DIR:-$HOME/backups/kisugu}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-84}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_FILE="$BACKUP_DIR/kisugu_media_${TIMESTAMP}.tar.gz"

if [ ! -d "$MEDIA_SOURCE" ]; then
  echo "Skipping media backup because '$MEDIA_SOURCE' does not exist."
  exit 0
fi

mkdir -p "$BACKUP_DIR"
tar -czf "$BACKUP_FILE" -C "$(dirname "$MEDIA_SOURCE")" "$(basename "$MEDIA_SOURCE")"
chmod 600 "$BACKUP_FILE"
find "$BACKUP_DIR" -type f -name 'kisugu_media_*.tar.gz' -mtime +"$BACKUP_RETENTION_DAYS" -delete

echo "Created media backup: $BACKUP_FILE"
