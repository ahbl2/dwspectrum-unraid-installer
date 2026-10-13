#!/bin/bash
# Read-only DW Spectrum audit: never restart, change configuration, or alter firewall.
set -euo pipefail
BASE=/boot/config/dwspectrum-quarantine
STATE=/boot/config/dwspectrum-quarantine/.monitor-status
NOTIFIED=/boot/config/dwspectrum-quarantine/.monitor-notified
STOP_NOTIFIED=/boot/config/dwspectrum-quarantine/.monitor-stop-notified
LOCK=/run/lock/dwspectrum-monitor.lock
mkdir -p /run/lock
exec 9>"$LOCK"
flock -n 9 || exit 0
status=OK
reason='recording protections verified'
if ! mountpoint -q /mnt/cache/dwspectrum-quarantine; then
  status=ALERT; reason='dedicated quarantine filesystem unmounted'
elif ! docker_state="$(timeout 12 docker inspect dwspectrum --format '{{.State.Running}}' 2>/dev/null)"; then
  status=ALERT; reason='Docker inspection failed; safeguards cannot be verified'
elif [[ "$docker_state" != true && "$docker_state" != false ]]; then
  status=ALERT; reason='Unexpected Docker state; safeguards cannot be verified'
elif [[ "$docker_state" == false ]]; then
  status=STOPPED; reason='DW Spectrum stopped; no automatic restart'
elif ! output="$(timeout --kill-after=3s 360s bash "$BASE/verify-view-only.sh" 2>&1)"; then
  status=ALERT; reason="view-only protection check failed: $(printf '%s' "$output" | tail -1 | cut -c 1-180)"
else
  used=""
  if ! used="$(df --output=pcent /mnt/cache/dwspectrum-quarantine | tail -1 | tr -dc '0-9')"; then
    status=ALERT; reason='could not read quarantine utilization'
  elif [[ -z "$used" ]]; then
    status=ALERT; reason='could not read quarantine utilization'
  elif (( used >= 80 )); then
    status=ALERT; reason="quarantine filesystem ${used}% used (threshold 80%)"
  fi
fi
previous="$(cat "$STATE" 2>/dev/null || true)"
current="$status | $reason"
if [[ "$previous" != "$current" ]]; then
  printf '%s\n' "$current" > "$STATE" 2>/dev/null || true
  logger -p "user.$([[ "$status" == ALERT ]] && echo err || echo notice)" -t dwspectrum-monitor -- "$current"
fi
notified="$(cat "$NOTIFIED" 2>/dev/null || true)"
if [[ "$status" != STOPPED ]]; then
  rm -f "$STOP_NOTIFIED" 2>/dev/null || true
fi
if [[ "$status" == ALERT && "$notified" != "$current" ]]; then
  if timeout --kill-after=3s 12s /usr/local/emhttp/webGui/scripts/notify -e 'DW Spectrum View-Only Guard' -s 'DW Spectrum recording safeguards FAILED' -d "$reason" -i alert >/dev/null 2>&1; then
    printf '%s\n' "$current" > "$NOTIFIED" 2>/dev/null || true
  else
    logger -p user.err -t dwspectrum-monitor 'Unraid notification failed; next check will retry'
  fi
elif [[ "$status" == STOPPED && "$(cat "$STOP_NOTIFIED" 2>/dev/null || true)" != "$current" ]]; then
  if timeout --kill-after=3s 12s /usr/local/emhttp/webGui/scripts/notify -e 'DW Spectrum Availability' -s 'DW Spectrum is stopped' -d 'No automatic restart; deliberate stops are respected.' -i warning >/dev/null 2>&1; then
    printf '%s\n' "$current" > "$STOP_NOTIFIED" 2>/dev/null || true
    if [[ "$notified" != ALERT* ]]; then
      printf '%s\n' "$current" > "$NOTIFIED" 2>/dev/null || true
    fi
  fi
elif [[ "$status" == OK && "$notified" != "$current" ]]; then
  if [[ "$notified" == ALERT* ]]; then
    if timeout --kill-after=3s 12s /usr/local/emhttp/webGui/scripts/notify -e 'DW Spectrum View-Only Guard' -s 'DW Spectrum safeguards restored' -d "$reason" -i normal >/dev/null 2>&1; then
      printf '%s\n' "$current" > "$NOTIFIED" 2>/dev/null || true
    else
      logger -p user.err -t dwspectrum-monitor 'Recovery notification failed; will retry'
    fi
  else
    printf '%s\n' "$current" > "$NOTIFIED" 2>/dev/null || true
  fi
fi
printf '%s\n' "$current"
[[ "$status" != ALERT ]]
