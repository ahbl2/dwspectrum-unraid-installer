#!/bin/bash
# DW Spectrum protected management. Never use unguarded docker compose up.
set -euo pipefail
BASE=/boot/config/dwspectrum-quarantine
case "${1:-help}" in
  start)
    [[ ! -e "$BASE/.pending-activation" ]] || { echo 'REFUSED: fresh installation requires guided activation' >&2; exit 42; }
    /bin/bash "$BASE/verified-start.sh"
    ;;
  stop)
    docker stop dwspectrum
    ;;
  status)
    echo "DW Spectrum container:"
    docker ps -a --filter name='^/dwspectrum$' --format '{{.Names}}: {{.Status}}'
    echo "Storage mount:"
    findmnt -rn -T /mnt/cache/dwspectrum-quarantine -o TARGET,SOURCE,FSTYPE,OPTIONS
    echo "Docker mounts (RW must be false except /dwdata/config):"
    docker inspect dwspectrum --format '{{range .Mounts}}{{.Destination}} writable={{.RW}} source={{.Source}}{{println}}{{end}}'
    ;;
  verify)
    /bin/bash "$BASE/verify-view-only.sh"
    ;;
  backup)
    # Bound tar, verification and every subprocess while keeping one lock owner.
    if [[ "${DW_BACKUP_WATCHDOG_CHILD:-}" != 1 ]]; then
      # Keep a parent alive outside timeout's process group to remove only this attempt's incomplete archive.
      umask 077
      pending="$(mktemp "$BASE/.config-backup-watched-XXXXXXXX.tar.gz")" || exit 42
      set +e
      timeout --signal=KILL --kill-after=5s 480s env DW_BACKUP_WATCHDOG_CHILD=1 DW_BACKUP_PENDING="$pending" /bin/bash "$0" backup
      result=$?
      set -e
      if [[ -e "$pending" ]]; then
        rm -f -- "$pending" || { echo 'CRITICAL: cannot remove incomplete backup archive' >&2; exit 42; }
      fi
      if [[ "$result" == 137 || "$result" == 124 ]]; then
        echo 'CRITICAL: backup watchdog expired; pending archive removed' >&2
      fi
      exit "$result"
    else
      [[ "$(readlink -f "/proc/$PPID/exe" 2>/dev/null)" == "$(readlink -f "$(command -v timeout)")" ]] || { echo 'REFUSED: backup watchdog bypass attempt' >&2; exit 42; }
      parent_args=()
      mapfile -d "" -t parent_args < "/proc/$PPID/cmdline" || { echo "REFUSED: backup parent argv unavailable" >&2; exit 42; }
      [[ "${parent_args[1]:-}" == "--signal=KILL" && "${parent_args[2]:-}" == "--kill-after=5s" && "${parent_args[3]:-}" == "480s" && "${parent_args[4]:-}" == "env" && "${parent_args[5]:-}" == "DW_BACKUP_WATCHDOG_CHILD=1" && "${parent_args[6]:-}" == "DW_BACKUP_PENDING=${DW_BACKUP_PENDING:-}" ]] || { echo "REFUSED: backup watchdog duration invalid" >&2; exit 42; }
    fi
    mkdir -p /run/lock
    exec 8>/run/lock/dwspectrum-config-operation.lock
    flock -n 8 || { echo 'REFUSED: guarded startup or backup in progress' >&2; exit 42; }
    [[ ! -e /run/dwspectrum-array-stopping ]] || { echo 'REFUSED: array shutdown in progress; backup denied' >&2; exit 42; }
    if compgen -G '/run/dwspectrum-stop-requests/*' >/dev/null; then echo 'REFUSED: pending array shutdown request; backup denied' >&2; exit 42; fi
    mountpoint -q /mnt/cache/dwspectrum-quarantine || { echo 'REFUSED: quarantine not mounted' >&2; exit 42; }
    [[ "$(findmnt -rn -T /mnt/cache/dwspectrum-quarantine -o FSTYPE)" == ext4 ]] || { echo 'REFUSED: non-ext4 storage' >&2; exit 42; }
    # Do not label a live archive application-consistent.
    if [[ "$(timeout 12 docker inspect dwspectrum --format '{{.State.Running}}' 2>/dev/null)" != false ]]; then
      echo 'REFUSED: consistent backup requires DW Spectrum stopped; manually stop it under an approved maintenance window' >&2
      exit 42
    fi
    umask 077
    stamp="$(date +%Y%m%d-%H%M%S)"
    output="$BASE/config-backup-$stamp.tar.gz"
    pending="${DW_BACKUP_PENDING:-}"
    [[ "$pending" == "$BASE/.config-backup-watched-"*".tar.gz" && -f "$pending" && ! -L "$pending" ]] || { echo 'REFUSED: validated pending backup archive missing' >&2; exit 42; }
    trap 'rm -f -- "$pending"' EXIT
    trap 'exit 42' HUP INT TERM
    if ! tar -czf "$pending" -C /mnt/cache/dwspectrum-quarantine config || ! python3 "$BASE/verify-backup.py" "$pending"; then
      rm -f -- "$pending"
      echo 'REFUSED: backup failed creation or integrity verification' >&2
      exit 42
    fi
    mv -n -- "$pending" "$output" || { rm -f -- "$pending"; exit 42; }
    [[ ! -e "$pending" ]] || { rm -f -- "$pending"; echo 'REFUSED: backup destination already exists' >&2; exit 42; }
    trap - EXIT HUP INT TERM
    echo "Configuration saved: $output"
    ;;
  help|*)
    echo 'Usage: bash /boot/config/dwspectrum-quarantine/manage.sh {status|verify|start|stop|backup}'
    exit 0
    ;;
esac
