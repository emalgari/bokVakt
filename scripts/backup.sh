#!/usr/bin/env bash
# Firmabok backup: consistent SQLite copy + uploads folder + manifest.
# Usage: scripts/backup.sh            (into data/backups/)
# Cron example (daily 21:00):
#   0 21 * * *  /path/to/firma/scripts/backup.sh >> /home/user/firma-backup.log 2>&1
set -euo pipefail
cd "$(dirname "$0")/.."

if command -v uv >/dev/null 2>&1 && [ -f "uv.lock" ]; then
  exec uv run python -m app.backup backup
else
  exec python3 -m app.backup backup
fi
