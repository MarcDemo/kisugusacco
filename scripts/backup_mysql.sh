#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$PROJECT_DIR/.env}"

if [ -f "$ENV_FILE" ]; then
  set -a
  . "$ENV_FILE"
  set +a
fi

DB_ENGINE_NORMALIZED="$(printf '%s' "${DB_ENGINE:-mysql}" | tr '[:upper:]' '[:lower:]')"
if [ "$DB_ENGINE_NORMALIZED" != "mysql" ] && [ "$DB_ENGINE_NORMALIZED" != "django.db.backends.mysql" ]; then
  echo "Skipping database backup because DB_ENGINE is '$DB_ENGINE'."
  exit 0
fi

: "${DB_NAME:?DB_NAME is required for MySQL backup.}"
: "${DB_USER:?DB_USER is required for MySQL backup.}"
: "${DB_PASSWORD:?DB_PASSWORD is required for MySQL backup.}"

DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-3306}"
BACKUP_DIR="${BACKUP_DIR:-$HOME/backups/kisugu}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-84}"
MYSQLDUMP_BIN="${MYSQLDUMP_BIN:-mysqldump}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_FILE="$BACKUP_DIR/kisugu_db_${DB_NAME}_${TIMESTAMP}.sql.gz"

mkdir -p "$BACKUP_DIR"

MYSQL_PWD="$DB_PASSWORD" "$MYSQLDUMP_BIN" \
  --single-transaction \
  --quick \
  --routines \
  --triggers \
  --default-character-set=utf8mb4 \
  -h "$DB_HOST" \
  -P "$DB_PORT" \
  -u "$DB_USER" \
  "$DB_NAME" | gzip > "$BACKUP_FILE"

chmod 600 "$BACKUP_FILE"
find "$BACKUP_DIR" -type f -name 'kisugu_db_*.sql.gz' -mtime +"$BACKUP_RETENTION_DAYS" -delete

echo "Created database backup: $BACKUP_FILE"

