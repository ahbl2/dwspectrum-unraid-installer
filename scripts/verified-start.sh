#!/bin/bash
set -euo pipefail
# Run the complete guarded start as a bounded process group before taking the lock.
# GNU timeout kills its command group, including children inheriting flock fd 8.
if [[ "${DW_START_WATCHDOG_CHILD:-}" != 1 ]]; then
  set +e
  timeout --signal=KILL --kill-after=5s 480s env DW_START_WATCHDOG_CHILD=1 /bin/bash "$0" "$@"
  result=$?
  set -e
  if [[ "$result" == 124 || "$result" == 137 ]]; then
    echo 'CRITICAL: guarded startup watchdog expired; verifying DW is stopped' >&2
    ( umask 077; touch /run/dwspectrum-startup-unsafe ) || exit 42
    mkdir -p /run/lock
    exec 7>/run/lock/dwspectrum-config-operation.lock
    flock -w 45 7 || { echo 'CRITICAL: startup lock remains held after timeout' >&2; exit 42; }
    containers="$(timeout --kill-after=3s 15s docker ps -a --format '{{.Names}}')" || { echo 'CRITICAL: cannot determine container state after timeout' >&2; exit 42; }
    if printf '%s\n' "$containers" | grep -Fxq dwspectrum; then
      state="$(timeout --kill-after=3s 15s docker inspect dwspectrum --format '{{.State.Running}}')" || exit 42
      if [[ "$state" == true ]]; then
        timeout --kill-after=5s 50s docker stop -t 30 dwspectrum >/dev/null || { echo 'CRITICAL: DW stop after watchdog timeout failed' >&2; exit 42; }
      fi
      [[ "$(timeout --kill-after=3s 15s docker inspect dwspectrum --format '{{.State.Running}}')" == false ]] || { echo 'CRITICAL: DW remains running' >&2; exit 42; }
    else
      filter_status=$?
      [[ "$filter_status" == 1 ]] || { echo 'CRITICAL: container filter failed after timeout' >&2; exit 42; }
    fi
    rm -f -- /run/dwspectrum-startup-unsafe
  fi
  exit "$result"
else
  [[ "$(readlink -f "/proc/$PPID/exe" 2>/dev/null)" == "$(readlink -f "$(command -v timeout)")" ]] || { echo 'REFUSED: startup watchdog bypass attempt' >&2; exit 42; }
  parent_args=()
  mapfile -d "" -t parent_args < "/proc/$PPID/cmdline" || { echo "REFUSED: startup parent argv unavailable" >&2; exit 42; }
  [[ "${parent_args[1]:-}" == "--signal=KILL" && "${parent_args[2]:-}" == "--kill-after=5s" && "${parent_args[3]:-}" == "480s" && "${parent_args[4]:-}" == "env" && "${parent_args[5]:-}" == "DW_START_WATCHDOG_CHILD=1" ]] || { echo "REFUSED: startup watchdog duration invalid" >&2; exit 42; }
fi
# Serialize guarded startup against consistent configuration backups.
mkdir -p /run/lock
exec 8>/run/lock/dwspectrum-config-operation.lock
flock -n 8 || { echo 'REFUSED: backup/startup operation already active' >&2; exit 42; }
[[ ! -e /run/dwspectrum-startup-unsafe ]] || { echo 'REFUSED: prior startup watchdog cleanup incomplete' >&2; exit 42; }
[[ ! -e /run/dwspectrum-array-stopping ]] || { echo 'REFUSED: Unraid array shutdown in progress' >&2; exit 42; }
if compgen -G '/run/dwspectrum-stop-requests/*' >/dev/null; then echo 'REFUSED: pending Unraid shutdown request' >&2; exit 42; fi
# Mount and verify the quarantine under the same operation lock used by Stop Array.
/bin/bash /boot/config/dwspectrum-quarantine/mount-storage.sh || { echo 'REFUSED: guarded quarantine mount failed' >&2; exit 42; }
BASE=/mnt/cache/dwspectrum-quarantine
IMAGE=/mnt/cache/dwspectrum-volume/storage.ext4
REPO=/boot/config/dwspectrum-quarantine
fail(){ echo "DW Spectrum startup REFUSED: $*" >&2; exit 42; }
if [[ -e "$REPO/.pending-activation" && "${DW_COMMISSIONING_BOOTSTRAP:-}" != ALLOW-INITIAL-START ]]; then
  fail 'fresh installation not activated; only the guided bootstrap/activate path may start it'
fi
[[ -f "$IMAGE" && -d "$BASE" ]] || fail "missing image or mountpoint"
[[ "$(stat -c %s "$IMAGE")" -eq 8589934592 ]] || fail "incorrect 8 GiB image size"
[[ "$(stat -c '%b %B' "$IMAGE" | awk '{print $1*$2}')" -ge 8589934592 ]] || fail "backing file not fully reserved"
[[ "$(lsattr -d "$IMAGE" | awk '{print $1}')" == *C* ]] || fail "NOCOW missing"
mountpoint -q "$BASE" || fail "ext4 quarantine is not mounted"
[[ "$(findmnt -rn -T "$BASE" -o FSTYPE)" == ext4 ]] || fail "unexpected filesystem"
SOURCE="$(findmnt -rn -T "$BASE" -o SOURCE)"
[[ "$SOURCE" == /dev/loop* ]] || fail "not loop device: $SOURCE"
[[ "$(losetup -n -O BACK-FILE "$SOURCE")" == "$IMAGE" ]] || fail "wrong loop backing file"
SIZE="$(df -B1 --output=size "$BASE" | tail -1 | xargs)"
[[ "$SIZE" -gt 7900000000 && "$SIZE" -lt 8700000000 ]] || fail "quarantine size unexpected: $SIZE"
[[ -d "$BASE/config" && -d "$BASE/media" ]] || fail "required folders missing"
[[ -f "$REPO/compose.yaml" ]] || fail "approved compose file missing"
# Verify the exact Compose mount topology before any start or recreation.
python3 - "$REPO/compose.yaml" <<'CHECK_COMPOSE' || fail "recording-proof Compose mounts invalid"
import json,subprocess,sys
config=json.loads(subprocess.check_output(['docker','compose','-f',sys.argv[1],'config','--format','json']))
service=config['services']['dwspectrum']
expected={'/dwdata':('/mnt/cache/dwspectrum-quarantine',True),'/dwdata/config':('/mnt/cache/dwspectrum-quarantine/config',False)}
actual={v['target']:(v['source'],bool(v.get('read_only',False))) for v in service['volumes']}
assert actual==expected,(actual,expected)
assert service.get('read_only') is True
assert service.get('restart')=='no'
# Docker rejects CPU quotas larger than available guest CPUs. Refuse before
# recreating a healthy stopped container; do not silently relax the quota.
import math
requested=service.get('cpus')
available_text=subprocess.check_output(['docker','info','--format','{{.NCPU}}'],text=True,timeout=15).strip()
available=int(available_text)
assert isinstance(requested,(int,float)) and not isinstance(requested,bool)
assert math.isfinite(float(requested)) and 0 < requested <= available, (
    f'REFUSED: Docker CPU request {requested} exceeds host capacity {available} or is invalid')
CHECK_COMPOSE
# In production the restart policy is deliberately NO; an absent mount after reboot must not start the container.
docker compose -f "$REPO/compose.yaml" config --quiet || fail "compose validation failed"
[[ ! -e /run/dwspectrum-array-stopping ]] || fail 'array shutdown began during guarded startup'
if compgen -G '/run/dwspectrum-stop-requests/*' >/dev/null; then fail 'new shutdown request during guarded startup'; fi
docker compose -f "$REPO/compose.yaml" up -d --no-build || fail "compose deployment failed"
[[ "$(docker inspect dwspectrum --format '{{.Config.User}}')" == 999:999 ]] || { docker stop dwspectrum; fail 'runtime user must remain 999:999'; }
[[ "$(docker inspect dwspectrum --format '{{.HostConfig.ReadonlyRootfs}}')" == true ]] || { docker stop dwspectrum; fail "Docker root is not read-only"; }
[[ "$(docker inspect dwspectrum --format '{{.HostConfig.RestartPolicy.Name}}')" == no ]] || { docker stop dwspectrum; fail "automatic restart unexpectedly enabled"; }
# Fail closed if Docker failed to realize the expected RO parent / RW config mounts.
if ! python3 - <<'CHECK_MOUNTS'
import json,subprocess
obj=json.loads(subprocess.check_output(['docker','inspect','dwspectrum']))[0]
expected={'/dwdata':('/mnt/cache/dwspectrum-quarantine',False),'/dwdata/config':('/mnt/cache/dwspectrum-quarantine/config',True)}
actual={m['Destination']:(m['Source'],m['RW']) for m in obj['Mounts']}
assert actual==expected,(actual,expected)
assert obj['HostConfig']['ReadonlyRootfs'] is True
assert obj['HostConfig']['CapDrop']==['ALL']
assert obj['HostConfig']['Privileged'] is False
assert 'no-new-privileges:true' in obj['HostConfig']['SecurityOpt']
assert obj['Config']['User']=='999:999'
CHECK_MOUNTS
then docker stop dwspectrum; fail "unexpected runtime mount or security settings"; fi
if docker exec -u 999:999 dwspectrum sh -c 'touch /dwdata/media/.dw-record-write-probe' >/dev/null 2>&1; then
  docker exec -u 999:999 dwspectrum rm -f /dwdata/media/.dw-record-write-probe || true
  docker stop dwspectrum; fail "archive path unexpectedly writable"
fi
if ! docker exec -u 999:999 dwspectrum sh -c 'test -w /dwdata/config'; then
  docker stop dwspectrum; fail "configuration directory not writable"
fi
# After commissioning, every guarded start must revalidate the live DW API/storage policy.
# During initial bootstrap/activation the marker remains present until the installer performs
# the credentialed audit and only then clears activation.
if [[ ! -e "$REPO/.pending-activation" ]]; then
  if ! /bin/bash "$REPO/verify-view-only.sh"; then
    if ! docker stop -t 30 dwspectrum >/dev/null 2>&1; then
      fail "post-start view-only verification failed; CRITICAL: container stop failed"
    fi
    [[ "$(docker inspect dwspectrum --format '{{.State.Running}}' 2>/dev/null)" == false ]] || fail "post-start view-only verification failed; CRITICAL: container still running"
    fail "post-start view-only verification failed"
  fi
fi
echo "DW Spectrum launched: read-only archive, config-only persistence, immutable root"
