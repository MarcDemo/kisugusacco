#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

if [ -f "$PROJECT_DIR/.env" ]; then
  set -a
  . "$PROJECT_DIR/.env"
  set +a
fi

if [ -d "$PROJECT_DIR/venv" ]; then
  . "$PROJECT_DIR/venv/bin/activate"
elif [ -d "$PROJECT_DIR/.venv" ]; then
  . "$PROJECT_DIR/.venv/bin/activate"
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  PYTHON_BIN="python"
fi

if [ "${RUN_PRE_DEPLOY_BACKUP:-0}" = "1" ]; then
  bash "$PROJECT_DIR/scripts/backup_mysql.sh"
fi

"$PYTHON_BIN" -m pip install --upgrade pip
"$PYTHON_BIN" -m pip install -r requirements-production.txt
"$PYTHON_BIN" manage.py migrate --noinput
"$PYTHON_BIN" manage.py collectstatic --noinput

if [ -n "${DJANGO_RESTART_COMMAND:-}" ]; then
  sh -c "$DJANGO_RESTART_COMMAND"
else
  mkdir -p "$PROJECT_DIR/tmp"
  touch "$PROJECT_DIR/tmp/restart.txt"
fi

echo "Deployment completed."
