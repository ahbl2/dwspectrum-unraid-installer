#!/bin/bash
# DW Spectrum: one-shot boot restoration, fails closed and respects subsequent manual stop.
set -euo pipefail
LOG=/boot/logs/dwspectrum-boot.log
DONE=/run/dwspectrum-boot-attempted
LOCK=/run/lock/dwspectrum-boot.lock
mkdir -p /boot/logs /run/lock
exec 9>"$LOCK"
flock -n 9 || exit 0
[[ ! -e "$DONE" ]] || exit 0
[[ ! -e /run/dwspectrum-array-stopping ]] || { echo 'REFUSED: array shutdown in progress' >&2; exit 42; }
# Restore the volatile Unraid plugin event handler on every boot.
EVENT_DIR=/usr/local/emhttp/plugins/dwspectrum-quarantine/event
EVENT_HOOK="$EVENT_DIR/stopping_svcs"
mkdir -p "$EVENT_DIR"
if [[ -e "$EVENT_HOOK" || -L "$EVENT_HOOK" ]]; then
  [[ -f "$EVENT_HOOK" && ! -L "$EVENT_HOOK" ]] || { echo 'REFUSED: invalid array stop hook' >&2; exit 42; }
  cmp -s "$EVENT_HOOK" <(printf '#!/bin/bash\n/bin/bash /boot/config/dwspectrum-quarantine/stop-storage.sh\n') || { echo 'REFUSED: conflicting array stop hook' >&2; exit 42; }
else
  printf '#!/bin/bash\n/bin/bash /boot/config/dwspectrum-quarantine/stop-storage.sh\n' > "$EVENT_HOOK"
fi
chmod 700 "$EVENT_HOOK"
for spec in stopped:array-stopped.sh docker_started:recover-after-docker-start.sh; do
  event="${spec%%:*}"
  script="${spec#*:}"
  event_file="$EVENT_DIR/$event"
  if [[ -e "$event_file" || -L "$event_file" ]]; then
    [[ -f "$event_file" && ! -L "$event_file" ]] || { echo 'REFUSED: invalid recovery event hook' >&2; exit 42; }
    cmp -s "$event_file" <(printf '#!/bin/bash\n/bin/bash /boot/config/dwspectrum-quarantine/%s\n' "$script") || { echo 'REFUSED: conflicting recovery event hook' >&2; exit 42; }
  else
    printf '#!/bin/bash\n/bin/bash /boot/config/dwspectrum-quarantine/%s\n' "$script" > "$event_file"
  fi
  chmod 700 "$event_file"
done
# Also trigger bounded recovery after Unraid's array "started" event, since
# docker_started can precede full array/Docker readiness.
event_file="$EVENT_DIR/started"
if [[ -e "$event_file" || -L "$event_file" ]]; then
  [[ -f "$event_file" && ! -L "$event_file" ]] || { echo 'REFUSED: invalid started event hook' >&2; exit 42; }
  cmp -s "$event_file" <(printf '#!/bin/bash\nnohup /bin/bash /boot/config/dwspectrum-quarantine/watch-array-lifecycle.sh recover </dev/null >>/run/dwspectrum-lifecycle.log 2>&1 &\n') || { echo 'REFUSED: conflicting started event hook' >&2; exit 42; }
else
  printf '#!/bin/bash\nnohup /bin/bash /boot/config/dwspectrum-quarantine/watch-array-lifecycle.sh recover </dev/null >>/run/dwspectrum-lifecycle.log 2>&1 &\n' > "$event_file"
fi
chmod 700 "$event_file"

# Fresh installations are held until administrator enrollment and verified activation.
if [[ -e /boot/config/dwspectrum-quarantine/.pending-activation ]]; then
  touch "$DONE"
  echo 'REFUSED: fresh DW installation has not passed activation' >&2
  exit 42
fi
say(){ printf '%s %s\n' "$(date -Is)" "$*" >> "$LOG"; logger -t dwspectrum-boot "$*"; }
# Only attempt during boot. A deliberate manual stop later won't cause a restart.
for n in $(seq 1 120); do
  if [[ -f /mnt/cache/dwspectrum-volume/storage.ext4 ]] && mountpoint -q /mnt/cache && timeout --kill-after=3s 12s docker info >/dev/null 2>&1; then
    if /bin/bash /boot/config/dwspectrum-quarantine/verified-start.sh >> "$LOG" 2>&1; then
      touch "$DONE"
      say "PASS: guarded boot start completed"
      exit 0
    fi
    # An unhealthy mount or failed container must never trigger a plain docker start.
    say "REFUSED: guarded startup failed; DW Spectrum will remain stopped"
    touch "$DONE"
    exit 42
  fi
  sleep 15
done
say "REFUSED: cache volume or Docker never became ready within boot window"
touch "$DONE"
exit 42
