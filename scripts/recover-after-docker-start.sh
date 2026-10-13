#!/bin/bash
# Docker started after an observed array stop: release only shutdown admission.
# Never start the DW container; an administrator must use guarded start.
set -euo pipefail
INTENT=/run/dwspectrum-array-stopping
[[ -e "$INTENT" ]] || exit 0
# The generation seen before taking the operation mutex may be superseded.
expected="$(cat "$INTENT")" || exit 42
[[ -n "$expected" ]] || exit 42
# Only the exact witnessed shutdown request may be cleared by recovery.
REQUESTS=/run/dwspectrum-stop-requests
fail(){ echo "REFUSED: shutdown recovery: $*" >&2; exit 42; }
[[ -e /run/dwspectrum-array-stopped-confirmed ]] || fail 'no verified array STOPPED event observed'
mkdir -p /run/lock
exec 8>/run/lock/dwspectrum-config-operation.lock
flock -n 8 || fail 'guarded operation in progress'
status="$(timeout --kill-after=3s 12s mdcmd status)" || fail 'array started state query failed'
state="$(printf '%s\n' "$status" | grep '^mdState=')" || fail 'mdState missing from completed query'
[[ "$state" == mdState=STARTED ]] || fail 'array is not STARTED'
[[ "$(timeout --kill-after=3s 12s findmnt -rn -T /mnt/cache -o TARGET,FSTYPE)" == '/mnt/cache btrfs' ]] || fail 'cache pool is not mounted as expected'
timeout --kill-after=3s 15s docker info >/dev/null 2>&1 || fail 'Docker is unavailable'
[[ ! -e /run/dwspectrum-startup-unsafe ]] || fail 'prior startup watchdog cleanup unresolved'
if timeout --kill-after=3s 12s mountpoint -q /mnt/cache/dwspectrum-quarantine; then
  fail 'quarantine is still mounted'
else
  probe_status=$?
  [[ "$probe_status" == 32 ]] || fail 'quarantine mountpoint verification failed'
fi
image=/mnt/cache/dwspectrum-volume/storage.ext4
[[ -f "$image" ]] || fail 'quarantine image missing'
loops="$(timeout --kill-after=3s 12s losetup -j "$image")" || fail 'cannot enumerate loop devices'
[[ -z "$loops" ]] || fail 'quarantine loop remains attached'
containers="$(timeout --kill-after=3s 15s docker ps -a --format '{{.Names}}')" || fail 'cannot enumerate containers'
if printf '%s\n' "$containers" | grep -Fxq dwspectrum; then
  [[ "$(timeout --kill-after=3s 15s docker inspect dwspectrum --format '{{.State.Running}}')" == false ]] || fail 'DW container is not stopped'
else
  filter_status=$?
  [[ "$filter_status" == 1 ]] || fail 'container enumeration filter failed'
fi
# The intent lock serializes the generation compare AND marker removal
# with every new Stop Array latch, eliminating a pre-operation-lock race.
exec 6>/run/lock/dwspectrum-intent.lock
flock 6 || fail 'cannot lock shutdown intent for recovery'
[[ "$(cat "$INTENT" 2>/dev/null)" == "$expected" ]] || fail 'new shutdown request superseded recovery'
[[ "$(cat /run/dwspectrum-array-stopped-confirmed 2>/dev/null)" == "$expected" ]] || fail 'stop witness does not match shutdown generation'
# Every published request must have completed before clearing historical latches.
# Keep descriptors locked through cleanup to prevent a new request being mistaken
# for a retired one. New requests published afterward remain independently visible.
shopt -s nullglob
request_files=( "$REQUESTS"/* )
request_fds=()
for request_file in "${request_files[@]}"; do
  [[ -f "$request_file" && ! -L "$request_file" ]] || fail 'invalid shutdown request marker'
  exec {request_fd}<"$request_file" || fail 'cannot open shutdown request marker'
  flock -n "$request_fd" || fail 'a shutdown callback is still active'
  request_fds+=( "$request_fd" )
done
[[ -f "$REQUESTS/$expected" ]] || fail 'witnessed shutdown request marker missing'
rm -f -- /run/dwspectrum-array-stopped-confirmed "$INTENT" "${request_files[@]}" || fail 'cannot clear recovery markers'
flock -u 6
echo 'PASS: verified array-up admission restored; DW remains manually stopped'
