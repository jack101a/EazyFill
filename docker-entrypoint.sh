#!/bin/sh
set -eu

seed_dir="/opt/eazyfill-seed"

seed_path() {
  src="$1"
  dst="$2"

  if [ -d "$src" ]; then
    mkdir -p "$dst"
    cp -an "$src/." "$dst/"
  fi
}

# Seed default config (no-clobber). Runtime data remains dynamic.
seed_path "$seed_dir/backend/config" "/app/backend/config"

# Ensure all required directories exist
mkdir -p /app/backend/logs \
         /app/backend/logs/backups/system \
         /app/backend/logs/backups/users \
         /app/backend/logs/backups/full \
         /app/backend/app/templates \
         /app/data/models

# Run Alembic migrations (skip in test mode)
if [ "${APP_ENV:-production}" != "test" ] && [ "${RUN_MIGRATIONS:-true}" != "false" ]; then
  echo "Running Alembic migrations..."
  cd /app/backend && python -m alembic upgrade head
  cd /app
fi

exec "$@"
