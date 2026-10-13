#!/bin/bash
# Unraid "stopped" event: record actual array-down evidence; never start DW.
set -euo pipefail
[[ -e /run/dwspectrum-array-stopping ]] || exit 0
# Serialize validation and witness publication against new Stop Array latches.
mkdir -p /run/lock
exec 8>/run/lock/dwspectrum-config-operation.lock
flock -n 8 || { echo 'REFUSED: shutdown operation lock busy' >&2; exit 42; }
[[ -e /run/dwspectrum-array-stopping ]] || exit 0
status="$(timeout --kill-after=3s 12s mdcmd status)" || { echo 'REFUSED: array stopped state query failed' >&2; exit 42; }
state="$(printf '%s\n' "$status" | grep '^mdState=')" || { echo 'REFUSED: mdState missing from completed query' >&2; exit 42; }
[[ "$state" == mdState=STOPPED ]] || { echo 'REFUSED: array-stopped event without verified STOPPED state' >&2; exit 42; }
exec 6>/run/lock/dwspectrum-intent.lock
flock 6 || { echo 'REFUSED: cannot lock shutdown generation' >&2; exit 42; }
generation="$(cat /run/dwspectrum-array-stopping)" || exit 42
[[ -n "$generation" ]] || exit 42
( umask 077; printf '%s\n' "$generation" > /run/dwspectrum-array-stopped-confirmed ) || exit 42
flock -u 6
echo 'PASS: Unraid array stopped evidence captured'
