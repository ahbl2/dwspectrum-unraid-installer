#!/usr/bin/env bash
# Offline diagnosis and rollback preparation only. Never silently restart.
set -euo pipefail
BASE=/boot/config/dwspectrum-quarantine
[[ "${1:-}" == plan && -n "${2:-}" ]] || { echo 'Usage: rollback-plan.sh plan /boot/config/dwspectrum-quarantine/rollout-backup-YYYYMMDD-HHMMSS' >&2; exit 42; }
backup="$2"
[[ "$backup" == "$BASE"/rollout-backup-* && -d "$backup" ]] || { echo 'REFUSED: approved backup directory required' >&2; exit 42; }
for f in compose.yaml verified-start.sh mount-storage.sh boot-start.sh verify-view-only.sh manage.sh monitor.sh check-record-storage.py; do
 [[ -s "$backup/$f" ]] || { echo "REFUSED: missing rollback artifact $f" >&2; exit 42; }
done
/bin/bash -n "$backup"/*.sh
if ! docker compose -f "$backup/compose.yaml" config --quiet; then echo 'REFUSED: backup Compose invalid' >&2; exit 42; fi
printf '%s\n' 'PASS: rollback artifacts appear complete. No files copied and no container stopped.' 'Restore requires separately approved maintenance procedure.'
