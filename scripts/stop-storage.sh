#!/bin/bash
set -u
# Each invocation owns a unique, non-reusable admission marker. Recovery must never
# erase a later request while completing an earlier array-start cycle.
REQUESTS=/run/dwspectrum-stop-requests
mkdir -p "$REQUESTS" /run/lock || exit 42
request_id="$(cat /proc/sys/kernel/random/uuid)" || exit 42
# Lock a private inode before atomically publishing the admission marker.
# A recovery scanner cannot mistake a newly published, pending request for stale.
request_pending="$(umask 077; mktemp /run/dwspectrum-request-XXXXXXXX)" || exit 42
exec 9>"$request_pending" || exit 42
flock 9 || exit 42
ln "$request_pending" "$REQUESTS/$request_id" || { echo 'CRITICAL: cannot publish shutdown request' >&2; exit 42; }
rm -f -- "$request_pending" || exit 42
# Signal shutdown before waiting for startup or backup operations.
INTENT=/run/dwspectrum-array-stopping
# Serialize intent generation changes with recovery's final marker clearance.
exec 6>/run/lock/dwspectrum-intent.lock
flock 6 || { echo 'CRITICAL: cannot lock shutdown intent' >&2; exit 42; }
rm -f -- /run/dwspectrum-array-stopped-confirmed || { echo 'CRITICAL: cannot invalidate old witness' >&2; exit 42; }
generation="$request_id"
( umask 077; printf '%s\n' "$generation" > "$INTENT" ) || { echo 'CRITICAL: shutdown intent cannot be established' >&2; exit 42; }
flock -u 6
exec 8>/run/lock/dwspectrum-config-operation.lock
echo 'DW quarantine shutdown: waiting for bounded guarded operation (up to 510s)' >&2
flock -w 510 8 || { echo 'CRITICAL: guarded operation lock timeout; refusing unsafe array shutdown (investigate active operation)' >&2; exit 42; }
# Reassert intent under the lock: an older recovery may have removed the first
# marker while this shutdown was waiting to acquire the lock.
flock 6 || { echo 'CRITICAL: cannot lock shutdown intent for relatch' >&2; exit 42; }
rm -f -- /run/dwspectrum-array-stopped-confirmed || { echo 'CRITICAL: cannot invalidate prior stop witness' >&2; exit 42; }
generation="$request_id"
( umask 077; printf '%s\n' "$generation" > "$INTENT" ) || { echo 'CRITICAL: cannot relatch shutdown intent' >&2; exit 42; }
flock -u 6
DATA=/mnt/cache/dwspectrum-quarantine
IMAGE=/mnt/cache/dwspectrum-volume/storage.ext4
log_msg(){ printf '%s\n' "$*"; logger -t dwspectrum-stop -- "$*" 2>/dev/null || true; }
fail(){ log_msg "DW quarantine shutdown REFUSED: $*"; exit 42; }
# Every Docker RPC has a client-side deadline, independent of daemon health.
# Never interpret an unavailable Docker daemon as proof that the container is absent.
if command -v docker >/dev/null 2>&1; then
  if CONTAINERS="$(timeout --kill-after=3s 15s docker ps -a --format '{{.Names}}' 2>/dev/null)"; then
    : # Docker daemon is responsive; inspect/stop below
  else
    [[ ! -S /var/run/docker.sock && ! -S /run/docker.sock ]] || fail "Docker daemon unavailable with socket present"
    PROCESSES="$(ps -eo comm=)" || fail "cannot enumerate runtime processes; refusing offline cleanup"
    if printf '%s\n' "$PROCESSES" | grep -Eq "^(dockerd|containerd|containerd-shim.*|dwspectrum|mediaserver)$"; then
      fail "Docker or DW runtime still has live processes; refusing offline cleanup"
    else
      FILTER_STATUS=$?
      [[ "$FILTER_STATUS" == 1 ]] || fail "runtime process filter failed; refusing offline cleanup"
    fi
    [[ -e "$INTENT" ]] || fail "offline cleanup requires shutdown intent"
    log_msg "Docker already stopped by Unraid; confirmed no Docker/DW runtime processes"
    CONTAINERS=""
  fi
  if printf '%s\n' "$CONTAINERS" | grep -Fxq dwspectrum; then
    STATE="$(timeout --kill-after=3s 15s docker inspect dwspectrum --format '{{.State.Running}}')" || fail "cannot inspect DW container"
    if [[ "$STATE" == true ]]; then
      timeout --kill-after=5s 50s docker stop -t 30 dwspectrum >/dev/null || fail "container did not stop cleanly"
      STATE="$(timeout --kill-after=3s 15s docker inspect dwspectrum --format '{{.State.Running}}')" || fail "cannot confirm container stopped"
      [[ "$STATE" == false ]] || fail "container still running"
    elif [[ "$STATE" != false ]]; then
      fail "unexpected container running status"
    fi
  else
    filter_status=$?
    [[ "$filter_status" == 1 ]] || fail "container name filter failed"
  fi
else
  fail "Docker CLI unavailable; cannot verify container state"
fi
if timeout --kill-after=3s 12s mountpoint -q "$DATA"; then
  quarantine_is_mounted=true
else
  mount_status=$?
  [[ "$mount_status" == 32 ]] || fail "quarantine mountpoint probe failed ($mount_status)"
  quarantine_is_mounted=false
fi
if [[ "$quarantine_is_mounted" == false ]]; then
  log_msg "DW quarantine shutdown: already unmounted; checking residual loops"
else
  [[ "$(timeout --signal=KILL --kill-after=3s 12s findmnt -rn -T "$DATA" -o FSTYPE)" == ext4 ]] || fail "quarantine filesystem query failed or is not ext4"
  SRC="$(timeout --signal=KILL --kill-after=3s 12s findmnt -rn -T "$DATA" -o SOURCE)" || fail "quarantine source query timed out or failed"
  [[ "$SRC" == /dev/loop* ]] || fail "quarantine is not loop-backed"
  BACKING="$(timeout --signal=KILL --kill-after=3s 12s losetup -n -O BACK-FILE "$SRC" 2>/dev/null)" || fail "loop backing file query timed out or failed"
  [[ "$BACKING" == "$IMAGE" ]] || fail "unexpected loop backing file"
  timeout --signal=TERM --kill-after=5s 60s sync -f "$DATA" || fail "quarantine filesystem sync failed or exceeded 60s"
  timeout --signal=TERM --kill-after=5s 60s umount "$DATA" || fail "quarantine unmount failed or exceeded 60s"
fi
LOOPS="$(timeout --signal=KILL --kill-after=3s 12s losetup -j "$IMAGE" 2>/dev/null)" || fail 'residual loop enumeration timed out or failed'
while IFS=: read -r LOOP _; do
  [[ -n "$LOOP" ]] || continue
  BACKING="$(timeout --signal=KILL --kill-after=3s 12s losetup -n -O BACK-FILE "$LOOP" 2>/dev/null)" || fail "residual loop backing query timed out or failed"
  [[ "$BACKING" == "$IMAGE" ]] || fail "unexpected residual loop device"
  if LOOP_MOUNTS="$(timeout --kill-after=3s 12s findmnt -rn -S "$LOOP" -o TARGET)"; then
    : # mount found; reject below
  else
    mount_probe_status=$?
    [[ "$mount_probe_status" == 1 ]] || fail "cannot check residual loop mounts"
    LOOP_MOUNTS=""
  fi
  [[ -z "$LOOP_MOUNTS" ]] || fail "residual loop remains mounted; refusing lazy detach"
  timeout --signal=KILL --kill-after=3s 12s losetup -d "$LOOP" 2>/dev/null || fail "residual loop detach timed out or failed"
done < <(printf '%s\n' "$LOOPS")
if timeout --kill-after=3s 12s mountpoint -q "$DATA"; then
  fail "quarantine still mounted"
else
  mount_status=$?
  [[ "$mount_status" == 32 ]] || fail "final quarantine mountpoint probe failed ($mount_status)"
fi
REMAINING="$(timeout --signal=KILL --kill-after=3s 12s losetup -j "$IMAGE" 2>/dev/null)" || fail 'final loop verification timed out or failed'
[[ -z "$REMAINING" ]] || fail "backing file still attached to loop device"
log_msg "PASS: DW quarantine detached for Unraid shutdown"
# Observe the actual STOPPED state asynchronously; never hold Unraid's event callback.
# Close flock fd 8 in the child, otherwise a witness can block the next guarded operation.
nohup /bin/bash /boot/config/dwspectrum-quarantine/watch-array-lifecycle.sh witness </dev/null >>/run/dwspectrum-lifecycle.log 2>&1 8>&- 9>&- &
